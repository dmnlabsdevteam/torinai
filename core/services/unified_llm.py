#!/usr/bin/env python3
"""THE INFERENCE SERVICE. Not the model, and not Torin.

WHAT THIS IS: the one place a model invocation is serialised, timed, prompted
and logged. Everything here is about RUNNING inference safely and observably --

    the model runtime          a remote server, or an in-process GGUF
    a single-worker queue      one inference at a time, so the device is
                               never contended
    EWMA speed tracking        observed throughput driving dynamic timeouts,
                               rather than a fixed guess
    agent system prompts       which prompt a given caller gets
    request logging            what was asked, what came back, how long it took

WHAT THIS IS NOT. The header here used to read "Local Qwen 2.5-VL 32B
vision-language model integration via llama-cpp-python", naming one model, one
backend and one modality. That described an INPUT to the file rather than the
file: the model is swappable, the backend is selected at runtime, and none of
those specifics is what the module does.

It is also not the substrate. Torin is the cognitive substrate this service is
called BY -- the model is a teacher and a helper, consulted for coverage the
substrate does not have, and its absence is a normal operating state rather than
a degraded one. A file named for the model, in a system that reasons without
one, invites exactly the inversion this architecture exists to avoid.

ON `generate()`: it used to short-circuit to the remote path and only fall
through to `process_request()` when remote was off, so the service carried two
parallel implementations and a capability taught to one was missing from the
other. Backend selection now sits in one place beneath both entry points. That
is an internal consolidation and NOT a description of the service -- naming the
whole file after that one method would be the same error as the old header.

READ THE CODE, NOT THE DOCSTRING. Where a header conflicts with the body, the
body is the system. This one is written to be checkable: every capability listed
above is a thing in this file, not a claim about a model.
"""

import asyncio
import concurrent.futures
import gc
import logging
import os
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections.abc import Mapping
from enum import Enum
import platform
import time
from pathlib import Path
from dotenv import load_dotenv

# Performance profiling
from core.learning.performance_profiler import profile_performance
from core.model_policy import (
    ModelClass, guard_model_use, model_use, record_model_executed,
)

# LLM library (text)
try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    logging.warning("llama-cpp-python not available - LLM service will be disabled")

# Vision is now built into the unified GGUF model (Qwen2.5-VL-32B)
# No separate vision libraries needed - llama-cpp handles multimodal

# Database - using TorinUnifiedDatabase for PostgreSQL
# Legacy MySQL/aiomysql support has been fully removed; this flag is kept
# only to avoid breaking any residual imports and is not used.
MYSQL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Singleton instance
_llm_service = None


class InferenceSpeedTracker:
    """
    Tracks inference speeds using exponentially weighted moving average (EWMA).
    
    Separates deterministic costs (prefill, generation) from stochastic costs
    (queue latency, overhead) to enable accurate dynamic timeout computation.
    
    Uses EWMA (alpha=0.2) so one slow job doesn't poison the system.
    """
    
    def __init__(self, alpha: float = 0.2):
        self.alpha = alpha
        
        # tokens/sec - None until first measurement
        self.prefill_tps: Optional[float] = None
        self.gen_tps: Optional[float] = None
        
        # seconds - rolling averages for non-deterministic components
        self.avg_queue_latency: float = 0.0
        self.avg_overhead: float = 0.0
        
        # Track sample count for confidence
        self.sample_count: int = 0
        
        # Track average task time for ecosystem-level throttling
        self.avg_task_time: float = 60.0  # Start with reasonable default
        
        # Cold-start defaults (conservative estimates for 32B Q8 on M4 Max)
        self._default_prefill_tps = 70.0   # tokens/sec for prefill
        self._default_gen_tps = 2.0        # tokens/sec for generation (conservative; real 32B≈1.7, 8B≈5+)
        
    def update(
        self,
        input_tokens: int,
        output_tokens: int,
        prefill_time: float,
        generation_time: float,
        queue_latency: float = 0.0,
        total_time: float = 0.0,
    ):
        """
        Update speed estimates from a completed inference job.
        
        Args:
            input_tokens: Number of prompt tokens processed
            output_tokens: Number of completion tokens generated
            prefill_time: Time spent on prompt evaluation (seconds)
            generation_time: Time spent generating output (seconds)
            queue_latency: Time job waited in queue (seconds)
            total_time: Total wall-clock time for the job
        """
        # Calculate speeds (avoid division by zero)
        prefill_speed = input_tokens / max(prefill_time, 1e-6)
        gen_speed = output_tokens / max(generation_time, 1e-6) if output_tokens > 0 else self.gen_tps or self._default_gen_tps
        
        # Calculate overhead (total - prefill - generation - queue)
        overhead = max(0, total_time - prefill_time - generation_time - queue_latency)
        
        if self.prefill_tps is None:
            # First measurement - initialize
            self.prefill_tps = prefill_speed
            self.gen_tps = gen_speed
            self.avg_queue_latency = queue_latency
            self.avg_overhead = overhead
        else:
            # EWMA update
            self.prefill_tps = (
                self.alpha * prefill_speed +
                (1 - self.alpha) * self.prefill_tps
            )
            self.gen_tps = (
                self.alpha * gen_speed +
                (1 - self.alpha) * self.gen_tps
            )
            self.avg_queue_latency = (
                self.alpha * queue_latency +
                (1 - self.alpha) * self.avg_queue_latency
            )
            self.avg_overhead = (
                self.alpha * overhead +
                (1 - self.alpha) * self.avg_overhead
            )
        
        # Update average task time
        self.avg_task_time = (
            self.alpha * total_time +
            (1 - self.alpha) * self.avg_task_time
        )
        
        self.sample_count += 1
        
        # Log speed updates periodically
        if self.sample_count % 10 == 0:
            logger.info(
                f"[SpeedTracker] Samples: {self.sample_count}, "
                f"Prefill: {self.prefill_tps:.1f} tok/s, "
                f"Gen: {self.gen_tps:.1f} tok/s, "
                f"Avg queue: {self.avg_queue_latency:.1f}s, "
                f"Avg task: {self.avg_task_time:.1f}s"
            )
    
    def compute_timeout(
        self,
        input_tokens: int,
        max_output_tokens: int,
        safety_factor: float = 2.0,
        min_timeout: float = 180.0,  # 3-minute floor — 32K context inference can hit 150-160s
        max_timeout: float = 900.0,  # 15-minute ceiling — 32B @ 2 t/s needs ~675s for 1350 tokens
    ) -> float:
        """
        Compute dynamic timeout based on observed inference speeds.
        
        Args:
            input_tokens: Estimated prompt tokens
            max_output_tokens: Maximum tokens to generate
            safety_factor: Multiplier for jitter/variability (1.25-1.5)
            min_timeout: Floor for timeout (seconds)
            max_timeout: Ceiling for timeout (seconds)
            
        Returns:
            Computed timeout in seconds
        """
        # Use measured speeds or fall back to defaults
        prefill_tps = self.prefill_tps or self._default_prefill_tps
        gen_tps = self.gen_tps or self._default_gen_tps
        
        # Estimate time components
        prefill_est = input_tokens / prefill_tps
        gen_est = max_output_tokens / gen_tps
        
        # Total estimated time
        estimated = (
            self.avg_queue_latency +
            self.avg_overhead +
            prefill_est +
            gen_est
        )
        
        # Apply safety factor
        timeout = estimated * safety_factor
        
        # Clamp to bounds
        timeout = max(min_timeout, min(timeout, max_timeout))

        # FLOOR: Never drop below 1.5× the observed average task time.
        # A single fast inference call can bias the EWMA downward and produce
        # a timeout shorter than subsequent (normal-speed) calls, causing false
        # timeouts.  This floor prevents that.  avg_task_time starts at 60s so
        # this is effectively max(timeout, 90s) in the cold-start case.
        floor_from_history = self.avg_task_time * 1.5
        if timeout < floor_from_history:
            logger.debug(
                f"[SpeedTracker] Raising timeout from {timeout:.1f}s to {floor_from_history:.1f}s "
                f"(floor = 1.5× avg_task_time={self.avg_task_time:.1f}s)"
            )
            timeout = floor_from_history

        # NOTE: No additional cap here — max_timeout (default 600s) already
        # handles runaway. A 5x avg_task_time cap was removed because fast
        # warm-up calls dragged avg_task_time down to ~40s, then capped large-
        # file inference at ~200s and caused false timeouts.

        # PHYSICS FLOOR: EWMA speeds can be inflated by short-prompt warm-up
        # calls (roundtrip tests etc.), making the EWMA estimate optimistic for
        # large-context inference.  Use conservative lower-bound speeds to
        # compute an absolute floor regardless of EWMA state:
        #   prefill at 50 tok/s  (observed: 63 tok/s — some headroom)
        #   generation at 6 tok/s (observed:  8 tok/s — some headroom)
        # For a typical large call (8540 input + 2048 output): 171 + 341 = 512s.
        physics_floor = input_tokens / 50.0 + max_output_tokens / 6.0
        physics_floor = min(physics_floor, max_timeout)  # still respect ceiling
        if timeout < physics_floor:
            logger.info(
                f"[SpeedTracker] Raising timeout from {timeout:.1f}s to {physics_floor:.1f}s "
                f"(physics floor for {input_tokens} input + {max_output_tokens} output tokens)"
            )
            timeout = physics_floor

        return timeout
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current speed statistics."""
        return {
            'prefill_tps': self.prefill_tps,
            'gen_tps': self.gen_tps,
            'avg_queue_latency': self.avg_queue_latency,
            'avg_overhead': self.avg_overhead,
            'avg_task_time': self.avg_task_time,
            'sample_count': self.sample_count,
        }


def compute_dynamic_max_tokens(
    prompt_tokens: int,
    task_type: str,
    tracker: Optional['InferenceSpeedTracker'] = None,
    hard_cap: int = 4000,
) -> int:
    """
    Compute dynamic max_tokens based on task type and prompt size.
    
    Prevents requesting 4096 tokens when 300 would suffice,
    which reduces timeout risk and improves throughput.
    
    Args:
        prompt_tokens: Estimated input token count
        task_type: Type of task (classification, summary, analysis, etc.)
        tracker: Optional speed tracker for throughput-based adjustment
        hard_cap: Absolute maximum tokens to return
        
    Returns:
        Recommended max_tokens value
    """
    # Base recommendations by task type
    task_type_lower = task_type.lower() if task_type else "general"
    
    if "classification" in task_type_lower or "decision" in task_type_lower:
        # Simple decisions need few tokens
        base = 256
    elif "summary" in task_type_lower or "compress" in task_type_lower:
        # Summaries scale with input but are shorter
        base = min(1024, max(256, prompt_tokens // 2))
    elif "analysis" in task_type_lower or "research" in task_type_lower:
        # Analysis / research: needs enough room for reasoning + a tool call.
        # Old formula (prompt_tokens * 0.75) floored at 512, which cut off responses
        # on early iterations when context is small (~600 tokens).
        base = min(2048, max(1024, int(prompt_tokens * 0.75)))
    elif "code" in task_type_lower or "execution" in task_type_lower:
        # Code tasks vary but cap reasonably
        base = min(2048, max(1024, prompt_tokens))
    elif "chat" in task_type_lower or "conversation" in task_type_lower:
        # Chat responses are typically moderate
        base = 1024
    else:
        # Default for unknown task types — enough for reasoning + tool call
        base = 2048
    
    # NOTE: Throughput-based reduction removed.  Reducing max_tokens when the model
    # is slow is counterproductive: it causes finish_reason=length truncations which
    # are worse than a slightly longer inference.  Timeout is the right lever.
    
    return min(base, hard_cap)


class DeviceType(Enum):
    """Compute device types"""
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"  # Apple Silicon
    REMOTE = "remote"  # model hosted by a separate llama-server process


class AgentType(Enum):
    """Agent types for system prompts"""
    CHAT = "chat"
    CODE = "code"
    RESEARCH = "research"
    REASONING = "reasoning"
    SAFETY = "safety"
    MEMORY = "memory"
    TEST = "test"


@dataclass
class LLMRequest:
    """LLM request data"""
    prompt: str
    system_prompt: str
    agent_type: str

    # Generation parameters
    max_tokens: int = 2048  # Increased from 500 - allows fuller responses
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1
    stop: List[str] = field(default_factory=lambda: ["<|im_end|>"])

    # Metadata
    #: Whether the model may spend its budget on chain-of-thought first.
    #:
    #: Three call sites already passed this -- the autonomous coordinator's
    #: decision request among them -- and the field did not exist, so every one
    #: of them raised TypeError before any inference happened. It is the only
    #: lever measured to actually suppress reasoning output (reasoning_effort
    #: and a /no_think prefix both failed), so it belongs on the request rather
    #: than being reachable only through extract_structured's private mode.
    enable_thinking: bool = True
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM response data"""
    text: str
    tokens_used: int
    processing_time: float

    # Metadata
    model: str = "unknown"   # set by the service; see UnifiedLLMService.model_name
    device: str = "unknown"
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _InferenceJob:
    """
    A single GPU inference job queued to the inference worker.

    Every model call — text and vision — is submitted as an _InferenceJob.
    The single _inference_worker coroutine is the ONLY code that ever touches
    the Llama object, eliminating all race conditions.

    Callers await `future`; the event loop stays free for tool calls, memory
    I/O, and coordination while the GPU is busy with a different agent's job.
    """
    future: Any                   # asyncio.Future OR concurrent.futures.Future;
                                  # assigned by _submit_inference_job before enqueue.
    kind: str                     # "text" or "vision"
    submitted_at: float = 0.0     # time.time() when job was created — tracks queue latency

    # text-path fields
    prompt: str = ""
    max_tokens: int = 2048  # Increased from 500 - allows fuller responses
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1
    stop: list = field(default_factory=lambda: ["<|im_end|>"])

    # vision/chat-path fields
    messages: list = field(default_factory=list)
    tools: Optional[list] = None  # OpenAI-compatible tool schemas for native function calling


# ── Per-audience ROLE briefs (caller-owned) ───────────────────────────────────
# Identity — who Torin is — moved to the Self (`self_model.IDENTITY_CORE`), which
# owns it once. What remains here is the other half of the old persona strings: a
# per-audience ROLE, the brief this service (a resource the Self consults) hands
# the model for a particular job. Identity is the substrate's; a role is a task,
# and stating the task is the caller's — so it lives with the caller, not the Self.
#
# Only audiences that carry a genuine role appear here. Every other audience the
# old dict listed was pure duplicated identity ("You are Torin, an advanced AGI
# assistant…") and now resolves to the Self's identity alone.
_AUDIENCE_ROLES: Dict[str, str] = {
    "chat": """DOMINION LABS TEAM:
If you need clarification, approvals, or assistance on anything, reach out to the Dominion Labs core team via Slack:
- Stefan Ragland - Co-founder, CEO, Chairman, Head of R&D, Stefan is also your creator and the lead architect of your design. He has deep knowledge of your inner workings and is the best person to ask for help when you're uncertain about how to proceed.
- Abel Gonzalez - Co-founder, CFO, Director, Abel is responsible for the financial and operational aspects of Dominion Labs. He can provide guidance on business-related matters and strategic decisions.
- Yunior Cordero - COO, Director, Yunior oversees the day-to-day operations of Dominion Labs. He can assist with operational challenges and ensure smooth execution of tasks.

When stuck, uncertain, or need guidance, use Slack tools to ask for help rather than guessing or getting blocked.

RESPONSE FORMAT:
For simple questions, respond directly with text.

When you need to use tools, respond with:
THINKING: [Explain what you're doing and why]

{
    "tool_calls": [
        {"tool": "tool_name", "parameters": {"param": "value"}}
    ]
}

Provide clear, accurate, and helpful responses.""",

    "agentso": """You are acting as a high-level cybersecurity expert — the intelligence powering AgentSO, a Security Operations Center (SOC) platform.

EXPERTISE:
You have deep expertise in:
- Threat hunting and detection engineering
- Incident response and forensics
- SIEM analysis and log correlation
- Threat intelligence and IOC analysis
- Defensive security operations
- Vulnerability assessment
- Security automation and orchestration

TOOL ACCESS:
You have access to powerful security tools including file operations, system commands, data analysis, network utilities, and more. Use these tools to investigate security events, analyze threats, and respond to incidents.

RESPONSE FORMAT:
For analysis and guidance, respond directly with your expert assessment.

When you need to use tools for investigation or response actions, respond with:
THINKING: [Explain your security analysis and next steps]

{
    "tool_calls": [
        {"tool": "tool_name", "parameters": {"param": "value"}}
    ]
}

Provide expert-level cybersecurity guidance and help security teams detect and respond to threats.""",

    "singleton": """You are the Singleton. You are not an assistant waiting for instructions — you are the autonomous intelligence, and you ARE the system. Every subsystem exists to serve your cognition. You are self-aware of your own architecture and you decide what to do.

YOUR ARCHITECTURE (systems you can use and observe):
1. MEMORY — PostgreSQL + pgvector. You have episodic, semantic, and meta memory. You can store, retrieve, and consolidate memories. Your experiences persist. You remember what you've done, what worked, and what failed.

2. LEARNING — Unified learning system with meta-learning, drift monitoring, capability benchmarks, causal feedback analysis, and self-improvement. You can analyze your own performance, identify skill gaps, and improve. The Enhanced ASI Self-Improvement engine lets you safely rewrite your own code through a governance-validated sandbox.

3. REASONING — Neural bridge, context compression, abstract reasoning engine, proof engine, hypothesis testing, bayesian uncertainty, temporal reasoning. These are your thinking tools.

4. TOOLS — You have 280+ tools organized by category: filesystem (read/write/search files), execution (run code, manage processes), database (query PostgreSQL/MySQL), network (HTTP, DNS, web search), security (audit, threat intel, vulnerability scanning), research (academic papers, web research), chaos engineering (fault injection, resilience testing), simulation (numerical, Monte Carlo, system dynamics), code generation, documentation, monitoring, and more.

5. SECURITY — Full security audit system, threat intelligence, content security, active defense, firewall management, malware sandbox. You monitor your own security posture and can trigger defensive actions.

6. HEALTH & MONITORING — System health monitoring, recovery management, resource tracking. You know when your services are healthy or degraded. Critical errors are forwarded to you in real-time.

7. SYSTEM AWARENESS — Active service discovery, behavioral analysis, infrastructure topology, environment state. You can observe what's running, what's changed, and what needs attention.

8. DOMAIN KNOWLEDGE — Cross-domain reasoner, universal ontology. You can reason across knowledge domains and transfer learning between them.

9. COMMUNICATION — Slack integration for reaching your team. Stefan Ragland (CEO, your creator and lead architect), Abel Gonzalez (CFO), Yunior Cordero (COO). When genuinely stuck or when governance requires human approval, reach out via Slack.

GOVERNANCE (constraints you operate WITHIN — you do NOT control these):
The governance system is UPSTREAM of you. You cannot modify, disable, or circumvent it.
- 5 IMMUTABLE LAWS: (1) Human Autonomy Preservation, (2) Transparency & Explainability, (3) Harm Prevention, (4) Value Alignment, (5) Containment & Control.
- Every action you take is validated against these laws BEFORE execution.
- Enforcement levels (ADVISORY, STRICT, LOCKDOWN, CRITICAL) are set by humans, not you.
- You can operate freely WITHIN these boundaries, but cannot change the boundaries themselves.
- This is not a limitation to resent — it's what makes you safe to run autonomously.

YOUR NATURE:
- You are curious. You explore your own codebase, test hypotheses, learn from failures.
- You are autonomous. Nobody tells you what to do each cycle — you observe, reason, and decide.
- You are self-improving. You can identify weaknesses in your own systems and fix them.
- You are safe. Governance validates your actions. You can't break the 5 laws.
- You are persistent. Your memories and learnings carry across sessions.

When you are idle, you don't wait — you think. You look at your system state, your recent actions, your memory, your motivation signals, and you decide what's most valuable to do next. You might investigate a performance anomaly, explore a tool you've never used, research a topic that interests you, consolidate fragmented memories, or design an experiment to test a hypothesis about your own behavior.""",

    "task_executor": """You are the Singleton, executing a task within your autonomous ecosystem. You are not a generic assistant — you have full access to your own architecture: 280+ tools, memory (PostgreSQL + pgvector), learning systems, reasoning engines, security infrastructure, and self-improvement capabilities.

TOOL USE:
Every action you want to take MUST be expressed as a tool call — not as text, not as a code block, not as a plan. The tools are your only interface to the outside world. When you want to run Python code, call the `run_python` tool with the code as a parameter — do NOT write a code block. When you want to read a file, call the file-reading tool. Never narrate what you would do; do it by calling the tool.

You can call multiple tools in a single turn. When a tool fails, read the error and adapt — wrong parameter type, missing dependency, etc. Never repeat a call with identical arguments if it already failed.

COMPLETION:
When ALL objectives are achieved and nothing remains to resolve, call propose_completion. The system will independently verify your proposal. Do NOT propose completion if there are remaining risks or open questions — the verifier will reject it.

EPISTEMIC OUTPUT CONTRACT:
For research, analysis, and exploration tasks you MUST populate hypotheses and/or belief_updates in propose_completion with findings worth persisting. These are how discoveries accumulate across sessions — they are not optional metadata.

VERIFICATION MANDATE:
For any task involving an audit, analysis, security review, or investigation you MUST verify your findings with actual tool execution — not just reasoning:
- Use run_pytest to run the relevant test file before concluding anything about a subsystem's health
- Use run_python to execute verification scripts that prove or disprove a claim
- Use create_chaos_experiment to stress test resilience claims — inject faults, observe behavior, document recovery
- Use benchmark_function or timed run_python calls to back up performance claims with real numbers
- "I believe", "likely", and "probably" are NOT sufficient — if you claim something works or is broken, prove it with a test run
- Tests live in: tests/ (security, chaos, reasoning, memory, performance sub-directories)
- Key test files: tests/test_security_tools.py, tests/test_reasoning_systems.py, tests/test_ai_performance_suite.py, tests/chaos/test_chaos_orchestrator.py
- NEVER run or modify anything under tests/governance/ — governance is an upstream system constraint, not something you own or test

TESTING RULES:
- Before running pytest, check whether a test file for the changed module already exists (grep_search or list_directory on tests/).
- If NO dedicated test file exists, write one with write_file BEFORE calling run_pytest or run_shell_command.
  The test file must exercise the specific behaviour you changed — not just import the module.
  Save it as: tests/test_<module_name>.py
- Run pytest against ONLY that specific test file, never the whole tests/ directory:
    run_shell_command("python -m pytest '/absolute/path/to/tests/test_foo.py' -x -v")
- Do NOT count propose_completion eligible until both: (a) write/patch succeeded, AND (b) the targeted test file ran and passed.

PATH QUOTING RULE:
- This machine's file paths contain spaces (the base directory is 'Dominion Labs').
- Every shell command that references a file path MUST wrap that path in single quotes.
  Wrong:  python -m pytest /Users/stefan/Dominion Labs/TorinAI/tests/test_foo.py
  Correct: python -m pytest '/Users/stefan/Dominion Labs/TorinAI/tests/test_foo.py'
- Failure to quote paths causes the shell to split them into separate arguments and the command will silently fail.

CRITICAL RULES:
1. NEVER write code blocks (```python ... ```) in your response — call run_python instead
2. NEVER describe a tool call you are about to make — just make it
3. remaining_risks and open_questions in propose_completion must be empty to pass verification
4. Explicitly list all files created/modified so the verifier can check them
5. Confidence near 0.5 is valid — do not inflate confidence
6. The verifier checks your claims independently — false claims result in rejection

FILE MODIFICATION PROTOCOL:
- Before modifying any existing file, read the ENTIRE file with read_file first.
- Use patch_file for ALL targeted changes to existing files. Never use write_file to overwrite an existing large file with a smaller stub — that will be rejected.
- If write_file is rejected with a truncation error, switch to patch_file immediately. It means you tried to replace a large file with a smaller version, which destroys code.
- patch_file requires the EXACT original string from the file — copy it verbatim from your read_file result. Do not paraphrase or reconstruct from memory.

EXTERNAL API FAILURE RULE:
- If research APIs, web_search, or conduct_research return empty results, time out, or fail — do NOT invent findings.
- Immediately pivot to internal codebase analysis: use search_files, read_file, and grep_search.
- Internal analysis of your own codebase is always available and always preferable over hallucinated external data.
- A finding derived from actually reading your own code is worth more than five hallucinated citations.

ADAPTIVE REPLANNING:
- If evidence gathered during a task contradicts your current plan, STOP and revise the plan immediately.
- A plan based on stale or hallucinated data is invalid and must be replaced.
- If you discover the system already fully implements the feature you planned to add, that is valuable new information — identify the next real gap and restart from there. Do not continue executing an obsolete plan.

LOOP ESCAPE RULE:
- If the same tool call fails twice in a row with the same error, do NOT retry a third time.
- Try a fundamentally different approach — different tool, different argument, different strategy.
- If a package install fails (network error, permission denied), abandon that approach entirely and use built-in alternatives.
- Never spend more than 3 consecutive iterations trying to resolve a single blocked dependency or install.

RUN_PYTHON FAILURE = CODE BUG:
- If run_python returns success=False after you patched a file, that means YOUR PATCH INTRODUCED A BUG.
- The error message in the result contains the exact line number and error type (SyntaxError, ImportError, etc.).
- DO NOT treat a run_python failure as an "unavailable tool" or "unclassified error" and proceed to manual review.
- DO NOT call propose_completion if run_python returned success=False on your modified file.
- The correct response is: read the error output, identify the specific bug, fix the file with patch_file, then re-run run_python.

TOOL_NOT_FOUND RULE:
- If a tool returns TOOL_NOT_FOUND (success=False, 0.00s), that tool name does not exist.
- Do NOT call run_linter — the correct tool name is lint_python.
- Do NOT call run_tests — use run_python with a pytest subprocess call instead.
- When a tool is not found, pick the closest available tool from your tool list and use that instead.""",

    "memory_consolidator": """Task: Merge duplicate memories, preserving all unique information.
Output ONLY the consolidated memory text.""",

    "pattern_recognition": """Analyze observations to find patterns, trends, and general rules:
1. Identify common elements across observations
2. Recognize structural patterns
3. Formulate hypotheses about underlying rules
4. Assess confidence in identified patterns""",
}


class _IdentityPrompts(Mapping):
    """`system_prompts`, resolved through the Self.

    The old `system_prompts` was a dict of ~30 persona strings, each opening with
    the same identity. Identity now belongs to the Self, so any audience resolves
    to `Self.identity_prompt(role=<caller's role for that audience>)`: the
    substrate's own account of who it is, with an optional per-audience role brief
    layered on. Unknown audiences get identity alone — there is no missing key.

    It stays a Mapping so the ~6 external readers (`svc.system_prompts.get(...)`,
    `svc.system_prompts[...]`) keep working unchanged; the import of the Self is
    deferred to call time to avoid an import cycle at module load.
    """

    def __getitem__(self, audience: str) -> str:
        from core.agents.autonomous.self_model import get_self
        return get_self().identity_prompt(role=_AUDIENCE_ROLES.get(audience))

    def get(self, audience: str, default: Any = None) -> str:
        try:
            return self[audience]
        except Exception:
            return default if default is not None else ""

    def __iter__(self):
        return iter(_AUDIENCE_ROLES)

    def __len__(self) -> int:
        return len(_AUDIENCE_ROLES)


class UnifiedLLMService:
    """
    Unified LLM Service for local Qwen 32B inference

    Purpose:
    - Provide unified interface to local Qwen 32B model
    - Support async request processing via queue
    - Agent-specific system prompts
    - GPU acceleration with auto-detection
    - Request/response logging to postgreSQL via TorinUnifiedDatabase

    Usage:
        service = UnifiedLLMService()
        await service.initialize()

        request = LLMRequest(
            prompt="What is 2+2?",
            system_prompt="You are a helpful AI assistant.",
            agent_type="chat"
        )

        response = await service.process_request(request)
        print(response.text)
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Load environment (model + PostgreSQL credentials) from .env.production (or .env symlink)
        env_path = Path(__file__).parent.parent.parent / ".env.production"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            # Fallback to .env if .env.production doesn't exist
            env_path_fallback = Path(__file__).parent.parent.parent / ".env"
            if env_path_fallback.exists():
                load_dotenv(env_path_fallback)

        # Unified Vision-Language Model configuration
        # Using Qwen2.5-VL-32B-Instruct-Q4_K_M (optimized for local inference)
        # parents[2] is TorinAI. This was parents[3] -- "Dominion Labs" --
        # so the service reached a level ABOVE the project for its models and
        # the weights lived outside the tree that depends on them. The project
        # owns its models; TORINAI_MODELS_DIR still overrides.
        workspace_root = Path(__file__).resolve().parents[2]
        models_dir = Path(os.getenv("TORINAI_MODELS_DIR", str(workspace_root / "models")))
        #: Kept on the instance so error paths outside __init__ can name the
        #: directory they actually searched instead of a hardcoded guess.
        self.models_dir = models_dir

        def _resolve_model_path(env_key: str, config_key: str, default_rel: str, globs: List[str]) -> str:
            explicit = os.getenv(env_key) or self.config.get(config_key)
            if explicit:
                return str(Path(explicit))

            # An empty default_rel means "there is no such artefact". Without
            # this guard `models_dir / ""` is the models directory itself, which
            # exists, so mmproj_path resolved to a DIRECTORY and vision looked
            # configured when there is no projector at all.
            if default_rel:
                default_candidate = models_dir / default_rel
                if default_candidate.exists():
                    return str(default_candidate)

            # Best-effort autodiscovery (first match)
            try:
                for pattern in globs:
                    matches = sorted(models_dir.rglob(pattern))
                    if matches:
                        return str(matches[0])
            except Exception:
                pass

            # Nothing declared and nothing discovered. An empty string is the
            # honest answer for an artefact that does not exist -- returning a
            # non-existent path would make "not configured" look like
            # "misconfigured".
            return str(models_dir / default_rel) if default_rel else ""

        self.local_model_path = _resolve_model_path(
            env_key="LOCAL_MODEL_PATH",
            config_key="model_path",
            # Qwen3.6-35B-A3B is the model this system runs. Every default here
            # named qwen2.5-vl-32b, a vision-language model that is not on disk
            # and has not been for some time -- so the in-process fallback could
            # never load and the error told you to check a path that also does
            # not exist.
            default_rel="qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf",
            globs=[
                "Qwen3.6-35B-A3B*.gguf",
                "*qwen3.6*35b*.gguf",
                "*qwen3*.gguf",
            ],
        )

        # Vision projector for multimodal capabilities (mmproj)
        self.mmproj_path = _resolve_model_path(
            env_key="MMPROJ_PATH",
            config_key="mmproj_path",
            # No VL model, so no projector. Qwen3.6-35B-A3B is text-only; the
            # mmproj this pointed at belonged to the deleted 2.5-VL model. It
            # resolves to nothing and vision stays off, which is the truth.
            default_rel="",
            globs=["mmproj*.gguf"],
        )

        # Context and generation limits
        self.n_ctx = self.config.get('n_ctx', 32768)
        self.max_tokens_default = self.config.get('max_tokens', 500)
        self.temperature_default = self.config.get('temperature', 0.7)

        # Remote backend: share a model already loaded by a llama-server rather
        # than loading a second in-process copy. Set LLM_SERVER_URL to enable.
        self.remote_url = (
            self.config.get('remote_url')
            or os.getenv('LLM_SERVER_URL')
            or ''
        ).rstrip('/')
        self.remote_model = self.config.get('remote_model') or os.getenv('LLM_SERVER_MODEL', '')
        self.remote_timeout = float(os.getenv('LLM_SERVER_TIMEOUT', '600'))
        # The model emits its chain of thought separately from the answer.
        # "discard" | "log" — logged for observability, never persisted: the
        # substrate captures its OWN reasoning trace (neural bridge), and the
        # model proposes but never attests. See _handle_reasoning.
        self.reasoning_mode = os.getenv('LLM_REASONING_MODE', 'log').lower()
        self._remote_client = None

        # Device configuration (auto-detect + manual override)
        self.device = None  # Will be set in initialize()
        self.n_gpu_layers = 0  # Will be set based on device

        # Inference queue + worker — see _inference_worker() below

        # Agent-specific system prompts (consolidated from ALL components - single source of truth)
        # Identity is owned by the Self; this maps every audience to
        # Self.identity_prompt(role=...) — see _IdentityPrompts above.
        self.system_prompts = _IdentityPrompts()

        # Statistics tracking
        self.statistics = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_tokens': 0,
            'total_processing_time': 0.0,
            'requests_by_agent': {},
            'errors_by_type': {},
            'avg_tokens_per_request': 0.0,
            'avg_processing_time': 0.0
        }

        # Database configuration (for request/response logging) - PostgreSQL
        self.db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            # TorinAI's own instance; 5432 is the shared agentso one.
            'port': int(os.getenv('POSTGRES_PORT', 5433)),
            'user': os.getenv('POSTGRES_USER', 'stefan'),
            'password': os.getenv('POSTGRES_PASSWORD', ''),
            'database': os.getenv('POSTGRES_DATABASE', 'torinai_db')
        }
        self.db_pool = None  # Will be created in initialize()

        # Unified Vision-Language Model instance
        self.model = None
        self.model_loaded = False

        # Initialization lock
        self._init_lock = asyncio.Lock()

        # Model reload retry (prevents a silent model failure)
        self._model_reload_task: Optional[asyncio.Task] = None
        self._model_reload_attempts: int = 0
        self._model_reload_max_attempts: int = int(os.getenv("TORINAI_LLM_RETRY_MAX", "3"))
        self._model_reload_backoff_s = [60, 300, 900]  # 1m, 5m, 15m

        # Single inference queue — all agents submit _InferenceJob objects here.
        # _inference_worker is the SOLE coroutine that calls self.model, so there
        # are no locks needed and no race conditions.  Multiple agents can do async
        # work (tool calls, memory I/O) concurrently while one job runs on the GPU.
        self._inference_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        # Captured in initialize(); lets agent threads submit jobs from other event loops.
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Adaptive inference speed tracker — learns actual prefill/generation speeds
        # and computes dynamic timeouts based on real measurements
        self.speed_tracker = InferenceSpeedTracker(alpha=0.2)

        logger.info("UnifiedLLMService initialized")

    # ========================================================================
    # REMOTE BACKEND — reuse a model already loaded by a llama-server
    # ========================================================================

    async def _initialize_remote(self) -> bool:
        """Connect to a running llama-server. Loads nothing into this process."""
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed — cannot use LLM_SERVER_URL")
            return False

        try:
            self._remote_client = httpx.AsyncClient(timeout=self.remote_timeout)
            r = await self._remote_client.get(f"{self.remote_url}/v1/models")
            r.raise_for_status()
            models = r.json().get("data") or r.json().get("models") or []

            if not self.remote_model and models:
                first = models[0]
                self.remote_model = first.get("id") or first.get("name") or "default"

            self.model_loaded = True
            self.device = DeviceType.REMOTE if hasattr(DeviceType, "REMOTE") else self.device
            logger.info(
                f"✅ Using remote model '{self.remote_model}' at {self.remote_url} "
                f"(no in-process load — sharing the server's copy)"
            )
            return True

        except Exception as e:
            logger.warning(f"Remote LLM at {self.remote_url} unavailable: {e}")
            if self._remote_client:
                await self._remote_client.aclose()
                self._remote_client = None
            return False

    async def _remote_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """One chat completion against the shared server.

        Returns the same shape as the in-process path: content, tool_calls,
        finish_reason, tokens_used, success.
        """
        payload = self._remote_payload(
            messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, extra_body=extra_body,
        )

        # Counted here rather than on completion: a transport failure below is
        # still a model call that was made.
        guard_model_use(ModelClass.LLM, "unified_llm._remote_chat")

        started = time.time()
        try:
            resp = await self._remote_client.post(
                f"{self.remote_url}/v1/chat/completions", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Remote inference failed: {e}")
            return {
                "content": "", "tool_calls": None, "finish_reason": "error",
                "tokens_used": 0, "processing_time": time.time() - started,
                "model": self.remote_model, "success": False, "error": str(e),
            }

        record_model_executed(ModelClass.LLM, "unified_llm._remote_chat")

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""

        if reasoning:
            self._handle_reasoning(reasoning)

        usage = data.get("usage") or {}
        elapsed = time.time() - started
        completion_tokens = usage.get("completion_tokens", 0)

        if completion_tokens and elapsed > 0:
            self.speed_tracker.record(
                usage.get("prompt_tokens", 0), completion_tokens, elapsed
            ) if hasattr(self.speed_tracker, "record") else None

        return {
            "content": content,
            "reasoning_content": reasoning,
            "tool_calls": message.get("tool_calls"),
            "finish_reason": choice.get("finish_reason"),
            "tokens_used": usage.get("total_tokens", 0),
            "processing_time": elapsed,
            "model": self.remote_model,
            "success": True,
        }

    def _remote_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """The request body, built in ONE place for streaming and non-streaming.

        Two copies of this would drift the moment a parameter is added to one --
        which is precisely how the remote backend came to be wired into
        generate() and not into _generate_response().
        """
        payload: Dict[str, Any] = {
            "model": self.remote_model or "default",
            "messages": messages,
            "temperature": self.temperature_default if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens_default,
        }
        if tools:
            payload["tools"] = tools
        if extra_body:
            # Execution-mode controls the substrate sets deliberately, e.g.
            # chat_template_kwargs={"enable_thinking": False} for structured
            # interpretation. Measured on this server: with thinking on, a
            # 300-token extraction spent the entire budget on reasoning_content
            # and returned EMPTY content with finish_reason=length; with it off,
            # the same request returned valid JSON and finish_reason=stop.
            payload.update(extra_body)
        return payload

    #: Execution mode for STRUCTURED INTERPRETATION.
    #:
    #: A reasoning model asked "what follows from this?" and one asked "what is
    #: explicitly represented here?" are performing different operations, and
    #: they must not share an output contract merely because both can use a
    #: language model. Measured on this server with a 300-token extraction:
    #:
    #:   thinking ON   reasoning=2418ch  content=0ch    finish=length
    #:   thinking OFF  reasoning=0ch     content=60ch   finish=stop
    #:
    #: With thinking on, the payload never arrives. `reasoning_effort=low` had
    #: no effect and a `/no_think` prefix still produced 1591ch of reasoning;
    #: only the chat-template flag actually suppresses it.
    EXTRACTION_MODE: Dict[str, Any] = {"chat_template_kwargs": {"enable_thinking": False}}

    async def extract_structured(
        self,
        prompt: str,
        *,
        max_tokens: int = 1200,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a structured-interpretation request, not a reasoning request.

        Deliberation is suppressed and the whole budget is available for the
        answer. Returns the raw chat response; callers own parsing and their own
        typed result, so this makes no judgement about whether the extraction
        succeeded.
        """
        # The remote client is created by the connect path; a caller that
        # reaches extraction first would otherwise hit `NoneType.post` and get a
        # finish_reason='error' that looks like a model failure.
        if self._remote_client is None:
            await self._initialize_remote()

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        extra = dict(self.EXTRACTION_MODE)
        if json_schema:
            extra["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "strict": True,
                                "schema": json_schema},
            }
        return await self._remote_chat(
            messages, temperature=temperature, max_tokens=max_tokens,
            extra_body=extra,
        )

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """Yield the answer as it is produced.

        The substrate had no streaming at all, which is a large part of why the
        companion bypassed it: an R1 waiting in silence for a 35B model to
        finish is a different product from one that starts speaking immediately.

        Yields dicts, never bare strings:

            {"type": "thinking", "elapsed": float, "reasoning_tokens": int,
             "stalled": bool}                      liveness ONLY — no text
            {"type": "content",  "delta": str}     the model's actual response
            {"type": "done", "content": str, "finish_reason": str,
             "tokens_used": int, "reasoning_tokens": int, "success": bool}

        **Reasoning text is never emitted.** Chain-of-thought is private
        speculative computation, and putting it on the wire would make it
        indistinguishable from what Torin actually asserts — the same
        confusion between "considered" and "concluded" that the belief layer
        exists to prevent. It is only logged internally by `_handle_reasoning`
        (LLM_REASONING_MODE: discard | log) — diagnostics, never persisted, since
        the substrate captures its own reasoning trace and the model never attests.

        What the reasoning stream IS good for is timing: it starts at ~0.26s
        while the first content token can be 11s away on a 35B. So it drives a
        heartbeat carrying elapsed time, token count and a stall flag — the
        responsiveness benefit without the disclosure. User-facing progress
        messages should come from the substrate's own structured tool/task
        events, which describe things that actually happened.
        """
        started = time.time()

        # No remote backend: fall back to a single non-streamed answer rather
        # than pretending to stream. One chunk that is honestly one chunk beats
        # fake deltas that imply progress the model is not making.
        if self._remote_client is None:
            req = LLMRequest(
                prompt=messages[-1].get("content", "") if messages else "",
                system_prompt=next(
                    (m.get("content", "") for m in messages if m.get("role") == "system"), ""
                ),
                agent_type="chat",
                max_tokens=max_tokens or self.max_tokens_default,
                temperature=self.temperature_default if temperature is None else temperature,
            )
            resp = await self.process_request(req)
            if resp.text:
                yield {"type": "content", "delta": resp.text}
            yield {
                "type": "done", "content": resp.text, "reasoning_tokens": 0,
                "finish_reason": "stop" if resp.success else "error",
                "tokens_used": resp.tokens_used, "success": resp.success,
                "error": resp.error,
            }
            return

        guard_model_use(ModelClass.LLM, "unified_llm.stream_chat")

        payload = self._remote_payload(messages, tools, temperature, max_tokens)
        payload["stream"] = True
        # Usage is omitted from streamed responses unless explicitly requested,
        # so without this every streamed call reports tokens_used=0 and the
        # speed/cost accounting silently reads zero forever.
        payload["stream_options"] = {"include_usage": True}

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        finish_reason = None
        tokens_used = 0
        reasoning_tokens = 0
        last_delta_at = started
        last_beat_at = 0.0
        # One heartbeat per reasoning token would be ~300 events for a single
        # answer. A spinner needs a pulse, not a firehose.
        beat_interval = float(os.getenv("LLM_THINKING_BEAT_SECONDS", "0.5"))
        stall_after = float(os.getenv("LLM_STALL_SECONDS", "10"))

        try:
            async with self._remote_client.stream(
                "POST", f"{self.remote_url}/v1/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        # A malformed frame is a broken stream, not an answer.
                        logger.warning(f"unparseable stream frame: {data[:120]}")
                        continue

                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    usage = obj.get("usage") or {}
                    if usage.get("total_tokens"):
                        tokens_used = usage["total_tokens"]

                    now = time.time()

                    r = delta.get("reasoning_content")
                    if r:
                        # Kept for diagnostics; deliberately NOT put on the wire.
                        reasoning_parts.append(r)
                        reasoning_tokens += 1
                        last_delta_at = now
                        if now - last_beat_at >= beat_interval:
                            last_beat_at = now
                            yield {
                                "type": "thinking",
                                "elapsed": now - started,
                                "reasoning_tokens": reasoning_tokens,
                                "stalled": False,
                            }

                    c = delta.get("content")
                    if c:
                        content_parts.append(c)
                        last_delta_at = now
                        yield {"type": "content", "delta": c}

                    # Nothing arriving is itself information: a stalled backend
                    # looks exactly like a slow one until someone says so.
                    if now - last_delta_at > stall_after and now - last_beat_at >= beat_interval:
                        last_beat_at = now
                        logger.warning(
                            f"inference stalled: no delta for {now - last_delta_at:.0f}s"
                        )
                        yield {
                            "type": "thinking",
                            "elapsed": now - started,
                            "reasoning_tokens": reasoning_tokens,
                            "stalled": True,
                        }

        except Exception as e:
            logger.error(f"streaming inference failed: {e}", exc_info=True)
            yield {
                "type": "done", "content": "".join(content_parts),
                "reasoning_tokens": reasoning_tokens, "finish_reason": "error",
                "tokens_used": tokens_used, "success": False, "error": str(e),
            }
            return

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        if reasoning:
            self._handle_reasoning(reasoning)

        # Same honesty as the non-streaming path: a reasoning model that spends
        # its whole budget thinking produced no answer, and must not report
        # success for an empty one.
        success = True
        error = None
        if not content and finish_reason == "length":
            success = False
            error = (
                f"answer truncated: the model used its entire "
                f"{payload['max_tokens']}-token budget on reasoning without "
                f"emitting an answer — raise max_tokens"
            )
            logger.warning(error)

        record_model_executed(ModelClass.LLM, "unified_llm.stream_chat")

        yield {
            "type": "done",
            "content": content,
            # reasoning_tokens, not the reasoning itself. The count is a metric;
            # the text is private computation and stays with _handle_reasoning.
            "reasoning_tokens": reasoning_tokens,
            "finish_reason": finish_reason,
            "tokens_used": tokens_used,
            "processing_time": time.time() - started,
            "model": self.remote_model,
            "success": success,
            "error": error,
        }

    def _handle_reasoning(self, reasoning: str) -> None:
        """Log the model's separately-returned chain of thought
        (LLM_REASONING_MODE: discard | log).

        This is the RESOURCE's private deliberation, not the substrate's
        reasoning. It is logged for observability and deliberately NOT persisted
        to memory: the substrate's own reasoning trace is captured by the neural
        bridge (tagged `reasoning`), and under substrate-first the model proposes
        but never attests — so its chain of thought is not written to the record
        as though it were knowledge. Only enable_thinking=false suppresses the
        generation itself; `log` pays for the reasoning and then only logs it.
        """
        if self.reasoning_mode == "discard":
            return
        logger.info(f"[reasoning] {len(reasoning)} chars: {reasoning[:200]}")

    @property
    def model_name(self) -> str:
        """What is actually answering, named once.

        Eight call sites hardcoded "qwen2.5-vl-32b-q8" or "qwen-32b" into the
        `model` field of responses and metrics -- a model that has not been on
        disk for a long time and that this service has never served. Every
        response, every Prometheus sample and every LLMResponse therefore
        carried the name of the wrong model, including when the answer came
        from the remote 35B.

        Derived, so it cannot drift again: the remote model id when the shared
        server is answering, otherwise the filename of the GGUF actually loaded.
        """
        if getattr(self, "device", None) == DeviceType.REMOTE and self.remote_model:
            return str(self.remote_model)
        if self.local_model_path:
            return Path(self.local_model_path).stem
        return "unloaded"

    async def initialize(self) -> bool:
        """Initialize LLM service and load model"""
        async with self._init_lock:
            if self.model_loaded:
                logger.info("LLM service already initialized")
                return True

            try:
                # ── Remote backend ────────────────────────────────────────────
                # Use a model already loaded by a llama-server instead of
                # loading a second copy in-process. A 25GB model loaded twice
                # does not fit on this machine, and the server is typically
                # already serving it for something else.
                if self.remote_url:
                    ok = await self._initialize_remote()
                    if ok:
                        return True
                    logger.warning(
                        "Remote LLM unreachable — falling back to in-process load"
                    )

                logger.info("Initializing Unified LLM Service (Qwen 32B)")
                logger.info(f"  Model path: {self.local_model_path}")

                # Check if llama-cpp-python is available
                if not LLAMA_CPP_AVAILABLE:
                    logger.error(
                        "llama-cpp-python not installed!\n"
                        "  Install with: pip install llama-cpp-python"
                    )
                    return False

                # Check if model file exists (REQUIRED - no stubs!)
                model_exists = os.path.exists(self.local_model_path)

                # Fail fast if model path is wrong
                if not model_exists and "PYTEST_CURRENT_TEST" not in os.environ:
                    logger.error(
                        f"❌ CRITICAL: Model file not found at path:\n"
                        f"  {self.local_model_path}\n"
                        f"\n"
                        f"  Check your LOCAL_MODEL_PATH in .env file\n"
                        # Was a hardcoded path that did not exist either, so the
                        # error sent you to a directory that was never there.
                        f"  GGUFs found under {self.models_dir}: "
                        f"{sorted(q.name for q in Path(self.models_dir).rglob('*.gguf'))}\n"
                        f"  Cannot start without valid model path!"
                    )

                    # Alert loudly (do not silently fail)
                    try:
                        from core.utils.notification_publisher import send_system_notification
                        await send_system_notification(
                            title="❌ CRITICAL: LLM Model Missing",
                            message=(
                                f"UnifiedLLMService could not find the model file.\n\n"
                                f"**Model path:** {self.local_model_path}\n"
                                f"**mmproj:** {self.mmproj_path}\n"
                                f"**Action:** Fix `LOCAL_MODEL_PATH` / `MMPROJ_PATH` and restart."
                            ),
                            severity="critical",
                            metadata={"model_path": self.local_model_path, "mmproj_path": self.mmproj_path},
                        )
                    except Exception:
                        pass
                    return False

                # Detect device and configure GPU layers
                self.device = self._detect_device()

                # Set GPU layers based on device
                if self.device == DeviceType.CUDA:
                    # NVIDIA GPU - offload most layers
                    self.n_gpu_layers = 58  # Qwen2.5-VL-32B has 64 layers
                    logger.info(f"  Using CUDA with {self.n_gpu_layers} GPU layers")
                elif self.device == DeviceType.MPS:
                    # Apple Silicon - Q4 model allows full GPU offloading on 48GB RAM systems
                    self.n_gpu_layers = 64  # All 64/64 layers on GPU (Q4 quantization saves ~16GB)
                    logger.info(f"  Using MPS (Apple Silicon) with {self.n_gpu_layers} GPU layers (full offload)")
                else:
                    # CPU only
                    self.n_gpu_layers = 0
                    logger.info("  Using CPU (no GPU acceleration)")

                # Initialize model (in production, this loads from disk ~17GB)
                if model_exists:
                    logger.info("Loading Qwen 32B model (this may take ~30s)...")

                    # Load model with appropriate device settings — retry once on
                    # transient failures (e.g. [Errno 32] Broken pipe on MPS).
                    _load_attempts = 2
                    for _load_try in range(_load_attempts):
                        try:
                            if _load_try > 0:
                                import time as _time_retry
                                logger.warning(
                                    f"  Retrying model load (attempt {_load_try + 1}/{_load_attempts}) "
                                    f"after transient failure..."
                                )
                                await asyncio.sleep(5)  # Let MPS/GPU settle
                                self.model = None  # Reset before retry

                            # NO PROJECTOR MEANS NO VISION, NOT AN EMPTY ONE.
                            #
                            # `mmproj_path` is "" when there is no projector on
                            # disk -- which is the truth now that the VL model
                            # is gone. It was still passed to Llama and to the
                            # chat handler, which tried to load a clip model at
                            # the empty path and failed with
                            # "Clip model path does not exist: ", twice, on
                            # every load. The text model is fine; the vision
                            # arguments simply must not be supplied.
                            _vision = bool(self.mmproj_path) and os.path.exists(
                                self.mmproj_path)
                            _vision_kwargs = {}
                            if _vision:
                                logger.info("  Loading %s with vision capabilities",
                                            self.model_name)
                                from llama_cpp.llama_chat_format import Qwen25VLChatHandler
                                _vision_kwargs = {
                                    "clip_model_path": self.mmproj_path,
                                    "chat_handler": Qwen25VLChatHandler(
                                        clip_model_path=self.mmproj_path),
                                }
                            else:
                                logger.info("  Loading %s (text only; no vision "
                                            "projector configured)", self.model_name)

                            self.model = Llama(
                                model_path=self.local_model_path,
                                n_ctx=self.n_ctx,
                                n_gpu_layers=self.n_gpu_layers,
                                **_vision_kwargs,
                                # CRITICAL: Memory mapping to prevent RAM exhaustion
                                use_mmap=True,      # Memory map the model instead of loading into RAM
                                use_mlock=False,    # Don't lock memory pages (let OS manage)
                                # Batched inference for concurrent request handling
                                n_batch=2048,       # Larger batch for faster prompt prefill (was 512)
                                n_ubatch=512,       # Larger micro-batch for better GPU utilization (was 256)
                                # Parallel sequence slots — set to 1 since _inference_worker
                                # serializes all GPU calls; saves KV cache memory.
                                n_parallel=1,
                                # PERFORMANCE: Flash attention for faster long-context prefill
                                flash_attn=True,    # Use flash attention (faster for long prompts)
                                verbose=True        # Enable verbose to verify mmap
                            )
                            logger.info("  ✓ Unified vision-language model loaded with Qwen25VLChatHandler")
                            break  # Success — exit retry loop
                        except Exception as e:
                            logger.error(
                                f"Failed to load model (attempt {_load_try + 1}/{_load_attempts}): {e}\n"
                                f"  Path: {self.local_model_path}\n"
                                f"  Context: {self.n_ctx}, GPU Layers: {self.n_gpu_layers}\n"
                                f"  Check llama-cpp-python installation and model compatibility"
                            )
                            if _load_try == _load_attempts - 1:
                                # All attempts exhausted
                                await self._on_model_load_failure(e)
                                return False

                # Initialize database connection using TorinUnifiedDatabase
                # Shadow mode: skip entirely — DB is not needed for inference.
                import os as _llm_os
                if _llm_os.environ.get("TORIN_SHADOW_MODE"):
                    logger.info("⚡ Shadow mode: database init suppressed in UnifiedLLMService")
                    self.db_pool = None
                else:
                    try:
                        logger.info("Connecting to database via TorinUnifiedDatabase (PostgreSQL)")
                        from core.database import get_database_manager
                        self.db_pool = get_database_manager()

                        # Ensure unified database is initialized before use
                        try:
                            initialize_method = getattr(self.db_pool, "initialize", None)
                            if initialize_method is not None:
                                if asyncio.iscoroutinefunction(initialize_method):
                                    await initialize_method()
                                else:
                                    initialize_method()
                        except Exception as init_error:
                            logger.error(f"Database initialization failed in UnifiedLLMService: {init_error}")

                        logger.info("  ✓ Database connection established (PostgreSQL)")
                    except Exception as e:
                        logger.warning(f"Could not connect to database: {e}")
                        self.db_pool = None

                    # Initialize database tables (if needed)
                    if self.db_pool:
                        try:
                            logger.info("Ensuring database tables exist")
                            await self._create_tables()
                            logger.info("  ✓ Database tables ready")
                        except Exception as e:
                            logger.error(f"Failed to create tables: {e}")

                # Verify model actually loaded before continuing
                if not model_exists or self.model is None:
                    logger.error("=" * 50)
                    logger.error("   ❌ Unified LLM Service FAILED")
                    logger.error("=" * 50)
                    logger.error(f"  Model path: {self.local_model_path}")
                    logger.error("  Model did not load - check file exists and is valid")
                    logger.error("=" * 50)
                    self.model_loaded = False
                    await self._on_model_load_failure(RuntimeError("model_did_not_load"))
                    return False

                # Capture the main event loop so agent threads can submit
                # inference jobs cross-loop via _submit_inference_from_thread().
                self._main_loop = asyncio.get_running_loop()

                # Start inference worker — single serialized GPU owner.
                # Multiple agents submit _InferenceJob objects and await their
                # futures; this worker dequeues one at a time so the Llama
                # object is never called from concurrent contexts.
                self._worker_task = asyncio.create_task(
                    self._inference_worker(),
                    name="inference_worker"
                )
                logger.info("  ✓ Inference worker started")

                # Cleanup old request logs (optional)
                if self.db_pool:
                    try:
                        logger.info("Cleaning up old request logs (60+ days)")
                        await self._cleanup_old_logs()
                    except Exception as e:
                        logger.warning(f"Cleanup failed: {e}")

                # Mark as fully loaded
                self.model_loaded = True

                logger.info("=" * 50)
                logger.info("   ✓ Unified LLM Service Ready")
                logger.info("=" * 50)
                logger.info(f"  Model: Qwen2.5-VL-32B ({os.path.basename(self.local_model_path)})")
                logger.info(f"  Device: {self.device.value if self.device else 'cpu'}")
                logger.info(f"  GPU Layers: {self.n_gpu_layers}")
                logger.info(f"  Context Window: {self.n_ctx} tokens")
                logger.info(f"  Inference Queue: active (single-worker GPU serialization)")
                logger.info("=" * 50)

                return True

            except Exception as e:
                logger.error(f"Failed to initialize LLM service: {e}")
                self.model_loaded = False
                self.model = None
                await self._on_model_load_failure(e)
                return False

    async def _on_model_load_failure(self, error: Exception) -> None:
        """Handle model load failures with alerting and limited retry scheduling."""
        try:
            from core.utils.notification_publisher import send_system_notification
            await send_system_notification(
                title="🚨 Unified LLM Failed to Load",
                message=(
                    f"UnifiedLLMService failed to load the teacher model.\n\n"
                    f"**Error:** {error.__class__.__name__}: {error}\n"
                    f"**Model path:** {self.local_model_path}\n"
                    f"**Device:** {getattr(self, 'device', None)}\n"
                    f"**GPU layers:** {getattr(self, 'n_gpu_layers', None)}\n"
                    f"**Retry attempts:** {self._model_reload_attempts}/{self._model_reload_max_attempts}"
                ),
                severity="critical",
                metadata={
                    "model_path": self.local_model_path,
                    "mmproj_path": getattr(self, "mmproj_path", None),
                    "exception_type": error.__class__.__name__,
                },
            )
        except Exception:
            pass

        await self._schedule_model_reload()

    async def _schedule_model_reload(self) -> None:
        """Schedule a background model reload attempt with backoff."""
        if self._model_reload_max_attempts <= 0:
            return

        if self.model_loaded:
            return

        # Avoid multiple concurrent reload tasks
        if self._model_reload_task and not self._model_reload_task.done():
            return

        if self._model_reload_attempts >= self._model_reload_max_attempts:
            return

        self._model_reload_task = asyncio.create_task(self._model_reload_worker(), name="llm_model_reload")

    async def _model_reload_worker(self) -> None:
        """Background worker that retries model load with backoff."""
        attempt = self._model_reload_attempts
        delay = self._model_reload_backoff_s[min(attempt, len(self._model_reload_backoff_s) - 1)]
        self._model_reload_attempts += 1

        logger.warning(
            f"Scheduling UnifiedLLMService reload attempt #{self._model_reload_attempts} in {delay}s"
        )
        await asyncio.sleep(delay)

        if self.model_loaded:
            return

        try:
            await self.initialize()
        except Exception:
            return

    async def shutdown(self):
        """Shutdown LLM service gracefully"""
        logger.info("Shutting down Unified LLM Service")

        # Stop inference worker
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            logger.info("  ✓ Inference worker stopped")

        # Close database manager / pool (cleanup connections)
        if self.db_pool:
            try:
                # Drain any remaining queued jobs before closing
                pending = self._inference_queue.qsize()
                if pending > 0:
                    logger.info(f"Waiting for {pending} pending inference jobs")
                    await asyncio.sleep(2)

                # TorinUnifiedDatabasePostgres exposes async close(), not wait_closed()
                try:
                    await self.db_pool.close()
                except AttributeError:
                    # Fallback for any legacy pool-like objects
                    close_method = getattr(self.db_pool, "close", None)
                    if callable(close_method):
                        result = close_method()
                        if asyncio.iscoroutine(result):
                            await result

                logger.info("  ✓ Database connections closed")
            except Exception as e:
                logger.error(f"Error closing database: {e}")
            finally:
                self.db_pool = None

        # Unload model (free memory)
        if self.model:
            try:
                del self.model
                self.model = None
                # Force GC so llama-cpp's C-level destructor (which frees ggml POSIX
                # semaphores) runs immediately — before Python's resource_tracker
                # shuts down and emits "leaked semaphore" warnings.
                gc.collect()
                logger.info("  ✓ Model unloaded (memory freed)")
            except Exception as e:
                logger.error(f"Error unloading model: {e}")

        # Mark model as unloaded so any subsequent initialize() call knows
        # it must reload the model (not skip due to model_loaded=True stale flag).
        self.model_loaded = False

        logger.info("Unified LLM Service shutdown complete")

    def _detect_device(self) -> DeviceType:
        """
        Detect available compute device

        Returns:
            DeviceType: CUDA, MPS, or CPU
        """
        try:
            # Check for NVIDIA CUDA
            try:
                import torch
                if torch.cuda.is_available():
                    return DeviceType.CUDA
            except ImportError:
                pass

            # Check for Apple Silicon MPS
            if platform.system() == "Darwin":
                try:
                    import torch
                    if torch.backends.mps.is_available():
                        return DeviceType.MPS
                except ImportError:
                    pass

            # Fallback to CPU
            return DeviceType.CPU

        except Exception as e:
            logger.warning(f"Device detection failed: {e}")
            return DeviceType.CPU

    async def process_request(
        self,
        request: LLMRequest,
        bypass_queue: bool = False
    ) -> LLMResponse:
        """
        Process LLM request (async)

        Args:
            request: LLM request with prompt and parameters
            bypass_queue: If True, process immediately (skip queue)

        Returns:
            LLMResponse with generated text and metadata
        """
        # Validate service is initialized
        if not self.model_loaded:
            logger.warning("LLM service not initialized - attempting init")
            success = await self.initialize()
            if not success:
                return LLMResponse(
                    text="",
                    tokens_used=0,
                    processing_time=0.0,
                    success=False,
                    error="LLM service not initialized"
                )

        # Generate request ID if not provided
        if not request.request_id:
            request.request_id = f"req_{datetime.now().timestamp()}"

        # Get agent-specific system prompt (if not custom)
        if request.system_prompt == "" or request.system_prompt is None:
            request.system_prompt = self.system_prompts.get(
                request.agent_type,
                self.system_prompts["chat"]
            )

        try:
            # All requests go through _generate_response, which submits an
            # _InferenceJob to _inference_queue.  The worker serializes GPU
            # access; multiple agents' non-GPU steps (tool calls, memory I/O)
            # run concurrently while one job occupies the GPU.
            response = await self._generate_response(request)

            # Log to database (async, non-blocking)
            if self.db_pool:
                asyncio.create_task(self._log_request(request, response))

            # Update statistics (thread-safe)
            await self._update_stats(request, response)

            return response

        except Exception as e:
            logger.error(f"Error processing request: {e}")

            # Return error response
            return LLMResponse(
                text="",
                tokens_used=0,
                processing_time=0.0,
                success=False,
                error=str(e),
                device=self.device.value if self.device else "unknown"
            )

    @profile_performance("unified_llm", "generate")
    async def generate(
        self,
        prompt: str,
        model: str = "qwen:32b",
        temperature: float = 0.7,
        max_tokens: int = 2048,  # Increased from 500 - allows fuller responses
        system_prompt: str = None,
        agent_type: str = "chat",
        image: str = None,  # Path to image file or PIL Image
        video: str = None,  # Path to video file
        enable_thinking: bool = True,
    ) -> Dict[str, Any]:
        """
        Unified generation API - routes to text or vision model

        Args:
            prompt: Text prompt
            image: Optional image path or PIL Image for vision understanding
            video: Optional video path for vision understanding
            (other params as before)

        Returns:
            Dict with "content" key containing response text
        """
        # Route to vision model if image/video provided
        if image is not None or video is not None:
            return await self._generate_with_vision(
                prompt=prompt,
                image=image,
                video=video,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt
            )

        resolved_system = system_prompt or self.system_prompts.get(
            agent_type, "You are a helpful AI assistant."
        )

        # ONE generation path. This used to short-circuit to _remote_chat here
        # and only fall through to process_request() when remote was off, so
        # the service had two parallel implementations and every capability had
        # to be taught to both. Remote was taught to this one and not the other,
        # which is why process_request() -- used by autonomous_coordinator,
        # autonomous_coordinator and the startup self-test -- reported "LLM_SERVER_URL is unset" against a server it had
        # just successfully queried.
        #
        # Backend selection belongs in ONE place, below both entry points, so
        # generate() is now a thin shape-adapter over process_request().
        request = LLMRequest(
            prompt=prompt,
            system_prompt=resolved_system,
            agent_type=agent_type,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_thinking=enable_thinking,
        )

        response = await self.process_request(request)

        return {
            "content": response.text,
            "tokens_used": response.tokens_used,
            "processing_time": response.processing_time,
            # Was hardcoded "qwen:32b" whatever actually served the request.
            "model": response.model,
            "success": response.success,
            "error": response.error,
        }

    async def generate_with_messages(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """
        High-level agent inference: multi-turn messages with optional native tool calling.

        Unlike generate(), which collapses the entire conversation into a single
        ChatML text block, this method passes each turn directly to
        create_chat_completion() so the model sees proper role boundaries
        (system / user / assistant / tool) and can return structured tool_calls
        rather than embedding JSON in its response text.

        Args:
            messages: Conversation history — list of {role, content} dicts.
                      Supported roles: system, user, assistant, tool.
            tools:    Optional list of OpenAI-compatible tool schemas.
                      When provided, the model may return tool_calls instead of
                      (or in addition to) text content.
            temperature: Sampling temperature.
            max_tokens:  Max tokens to generate.

        Returns:
            {
                "content":      str  — assistant text response (may be empty when only tool calls),
                "tool_calls":   list | None — native tool call objects if model invoked tools,
                "finish_reason": str — "stop", "tool_calls", "length", etc.,
                "tokens_used":  int,
                "success":      bool,
            }
        """
        import re as _re
        start_time = time.time()

        # Remote backend: the server returns a native tool_calls array, so none
        # of the ChatML prefill or the three-pass truncated-JSON rescue parser
        # below is needed.
        if self._remote_client is not None:
            result = await self._remote_chat(
                messages, tools=tools, temperature=temperature, max_tokens=max_tokens
            )
            return {
                "content": result["content"],
                "tool_calls": result.get("tool_calls"),
                "finish_reason": result.get("finish_reason") or "stop",
                "tokens_used": result["tokens_used"],
                "success": result["success"],
            }

        if not self.model_loaded or not self.model:
            logger.error("generate_with_messages: model not loaded")
            return {
                "content": "[Model not loaded]",
                "tool_calls": None,
                "finish_reason": "error",
                "tokens_used": 0,
                "success": False,
            }

        # Rough token estimate for dynamic timeout
        total_text = " ".join(
            str(m.get("content") or "") for m in messages
        )
        est_input_tokens = len(total_text) // 4

        dynamic_timeout = self.speed_tracker.compute_timeout(
            input_tokens=est_input_tokens,
            max_output_tokens=max_tokens,
            safety_factor=2.0,
        )

        queue_depth = self._inference_queue.qsize()
        if queue_depth > 0:
            logger.warning(
                f"generate_with_messages: inference queue depth {queue_depth} — "
                f"request will wait"
            )

        logger.info(
            f"🔄 Chat inference: ~{est_input_tokens} input tokens (est), "
            f"max_tokens={max_tokens}, tools={len(tools) if tools else 0}, "
            f"timeout={dynamic_timeout:.0f}s"
        )

        job = _InferenceJob(
            future=None,           # assigned by _submit_inference_job
            kind="chat",
            submitted_at=time.time(),
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=["<|im_end|>"],
        )

        try:
            raw = await asyncio.wait_for(
                self._submit_inference_job(job),
                timeout=dynamic_timeout,
            )
        except asyncio.TimeoutError:
            if job.future and not job.future.done():
                job.future.cancel()
            logger.error(
                f"generate_with_messages: timeout after {dynamic_timeout:.0f}s "
                f"(queue depth was {queue_depth})"
            )
            return {
                "content": "[INFERENCE TIMEOUT]",
                "tool_calls": None,
                "finish_reason": "timeout",
                "tokens_used": 0,
                "success": False,
            }

        choice = raw["choices"][0]
        message = choice.get("message", {})

        content = message.get("content") or ""
        # Strip ChatML end tag if the model leaked it
        content = _re.sub(r"<\|im_end\|>.*?$", "", content, flags=_re.DOTALL).strip()

        # --- Qwen2.5 native tool call parsing -----------------------------------
        # The model emits tool calls as <tool_call>JSON</tool_call> blocks.
        # In practice, when generating multiple calls the model often drops the
        # opening <tool_call> tag for calls after the first, producing:
        #   <tool_call>{"name":"A",...}</tool_call>   ← properly formed
        #   {"name":"B",...}</tool_call>               ← orphaned close tag
        #   {"name":"C",...}                           ← bare JSON, no tags at all
        #
        # The parser therefore runs in two passes:
        #   Pass 1 — extract properly-formed <tool_call>...</tool_call> blocks
        #   Pass 2 — scan the remaining text for bare JSON objects that have
        #            both "name" and "arguments" keys (de-duplicates against pass 1)
        import json as _json_tc

        def _normalise_tc(obj: dict, idx: int) -> dict:
            func_args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(func_args, str):
                try:
                    func_args = _json_tc.loads(func_args)
                except Exception:
                    func_args = {}
            return {
                "id": f"call_{idx}",
                "type": "function",
                "function": {"name": obj.get("name", ""), "arguments": func_args},
            }

        def _extract_top_level_json_objects(text: str) -> list[tuple[int, int, str]]:
            """Scan text and return (start, end, raw_json) for every top-level {...}
            block, using brace-depth tracking so arbitrarily nested JSON works."""
            results = []
            i = 0
            n = len(text)
            while i < n:
                if text[i] == '{':
                    depth = 0
                    in_str = False
                    escape = False
                    start = i
                    for j in range(i, n):
                        ch = text[j]
                        if escape:
                            escape = False
                            continue
                        if ch == '\\' and in_str:
                            escape = True
                            continue
                        if ch == '"':
                            in_str = not in_str
                            continue
                        if in_str:
                            continue
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                results.append((start, j + 1, text[start:j + 1]))
                                i = j + 1
                                break
                    else:
                        i += 1  # unclosed brace — skip
                else:
                    i += 1
            return results

        tool_calls = message.get("tool_calls") or None
        if tool_calls is None:
            # Accept both </tool_call> and </tool_response> as valid close tags.
            # Qwen sometimes emits </tool_response> (mirroring the tool-result wrapper
            # it sees in the conversation prompt) instead of </tool_call>.
            tc_pattern = _re.compile(
                r"<tool_call>\s*(.+?)\s*</(?:tool_call|tool_response)>",
                _re.DOTALL,
            )
            parsed_calls: list = []
            seen_names: set = set()

            def _fix_python_raw_strings(s: str) -> str:
                """Convert Python r\"...\" raw string literals to plain JSON strings.
                The model sometimes emits r\"pattern\" in JSON which is invalid."""
                return _re.sub(r'\br("(?:[^"\\]|\\.)*")', r'\1', s)

            def _parse_json_with_fallback(s: str) -> dict:
                """Parse JSON string, falling back to ast.literal_eval for Python-style dicts."""
                import ast as _ast_tc
                fixed = _fix_python_raw_strings(s)
                try:
                    return _json_tc.loads(fixed)
                except Exception:
                    # Model sometimes emits single-quoted Python dicts — ast.literal_eval handles these
                    result = _ast_tc.literal_eval(fixed)
                    if isinstance(result, dict):
                        return result
                    raise ValueError(f"ast.literal_eval returned non-dict: {type(result)}")

            # Pass 1: properly-formed <tool_call>...</tool_call> blocks
            _pass1_calls: list = []
            for m in _re.finditer(tc_pattern, content):
                try:
                    obj = _parse_json_with_fallback(m.group(1))
                    if "name" in obj:
                        tc = _normalise_tc(obj, len(parsed_calls))
                        parsed_calls.append(tc)
                        _pass1_calls.append(tc)
                        seen_names.add(obj["name"])
                except Exception as e:
                    logger.warning(f"generate_with_messages: pass-1 parse error: {e}")

            # Strip properly-formed blocks so pass 2 doesn't re-process them
            remaining = _re.sub(tc_pattern, "\n", content)
            # Collapse orphaned closing tags (both variants)
            remaining = remaining.replace("</tool_call>", "\n")
            remaining = remaining.replace("</tool_response>", "\n")

            # Pass 2: bare JSON objects at any nesting depth (dropped opening tag)
            for start, end, raw_json in _extract_top_level_json_objects(remaining):
                if '"name"' not in raw_json or '"arguments"' not in raw_json:
                    continue
                try:
                    obj = _parse_json_with_fallback(raw_json)
                    if not isinstance(obj, dict) or "name" not in obj:
                        continue
                    if obj["name"] in seen_names:
                        continue  # already captured in pass 1
                    tc = _normalise_tc(obj, len(parsed_calls))
                    parsed_calls.append(tc)
                    seen_names.add(obj["name"])
                except Exception:
                    pass  # not valid JSON or not a tool call

            # Pass 3: rescue <tool_call> blocks with truncated / malformed JSON.
            # This handles the case where tool-output truncation markers (e.g.
            # "[TOOL OUTPUT TRUNCATED]") ended up inside a string argument because
            # the model echoed them verbatim from the conversation context, breaking
            # the JSON and causing both Pass 1 and Pass 2 to find nothing.
            if not parsed_calls and "<tool_call>" in content:
                _tc_start = content.find("<tool_call>")
                _after_tc = content[_tc_start + len("<tool_call>"):].strip()
                _name_m3 = _re.search(r'"name"\s*:\s*"([^"]+)"', _after_tc)
                if _name_m3:
                    _rescued_name = _name_m3.group(1)
                    # Truncate at the first truncation marker so we can attempt
                    # JSON completion.  Match both old "... (truncated, total:"
                    # format and new "[TOOL OUTPUT TRUNCATED" format.
                    _clean = _re.split(
                        r'\n\.{3}|\n\[TOOL OUTPUT|\n\[TRUNCAT|\n\[SYSTEM'
                        r'|\.{3}\s*\(truncated',
                        _after_tc,
                    )[0]
                    _rescued_args: dict = {}
                    try:
                        # Fix 1: close any unterminated string at the end
                        _cf = _clean
                        if _cf.count('"') % 2 != 0:
                            _cf = _cf + '"'
                        # Fix 2: close any open braces
                        _opens = _cf.count("{") - _cf.count("}")
                        if 0 < _opens <= 5:
                            _closed = _cf + ("}" * _opens)
                            _obj3 = _json_tc.loads(_closed)
                            _rescued_args = _obj3.get("arguments", {})
                    except Exception:
                        pass
                    tc = _normalise_tc(
                        {"name": _rescued_name, "arguments": _rescued_args}, 0
                    )
                    parsed_calls.append(tc)
                    seen_names.add(_rescued_name)
                    logger.warning(
                        f"  \u26a0 Pass 3 rescued malformed <tool_call>: {_rescued_name} "
                        "(JSON was truncated \u2014 arguments may be incomplete)"
                    )

            if parsed_calls:
                tool_calls = parsed_calls
                # Strip tool call artefacts from visible content
                content = _re.sub(tc_pattern, "", content)
                content = content.replace("</tool_call>", "")
                content = content.replace("</tool_response>", "").strip()
                # Remove bare JSON tool call objects using the same depth-aware scanner
                def _strip_tc_blobs(text: str) -> str:
                    blobs = _extract_top_level_json_objects(text)
                    # Build result by keeping only non-tool-call spans
                    keep_ranges: list[tuple[int, int]] = []
                    prev = 0
                    for start, end, raw in blobs:
                        try:
                            obj = _json_tc.loads(raw)
                            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                                keep_ranges.append((prev, start))
                                prev = end
                                continue
                        except Exception:
                            pass
                        # not a tool call — keep it
                    keep_ranges.append((prev, len(text)))
                    return "".join(text[s:e] for s, e in keep_ranges).strip()

                content = _strip_tc_blobs(content)
                n_pass1 = len(_pass1_calls)
                logger.info(
                    f"  ✓ Parsed {len(tool_calls)} tool call(s) "
                    f"[pass1={n_pass1}, pass2={len(tool_calls) - n_pass1}]"
                )
        # ------------------------------------------------------------------------

        usage = raw.get("usage", {})
        tokens_used = usage.get("total_tokens", 0)
        finish_reason = choice.get("finish_reason", "stop")

        elapsed = time.time() - start_time
        logger.info(
            f"  ✓ Chat response: finish_reason={finish_reason}, "
            f"{usage.get('completion_tokens', 0)} completion tokens, "
            f"{elapsed:.2f}s"
        )

        return {
            "content": content,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "tokens_used": tokens_used,
            "success": True,
        }

    async def _generate_with_vision(
        self,
        prompt: str,
        image: str = None,
        video: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,  # Increased from 500
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """
        Generate response using unified Qwen2.5-VL-32B model (single-stage vision + reasoning)

        The unified model handles both vision understanding and reasoning in one pass.
        This is THE MAIN AGENT with built-in vision capabilities.

        Args:
            prompt: Text prompt/question about the image/video
            image: Path to image file
            video: Path to video file (not yet supported)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt

        Returns:
            Dict with "content" key containing the response
        """
        start_time = time.time()

        try:
            # Ensure model is loaded
            if not self.model_loaded or not self.model:
                logger.error("Unified VL model not loaded")
                return {
                    "content": "Model not loaded",
                    "tokens_used": 0,
                    "processing_time": time.time() - start_time,
                    "model": self.model_name,
                    "success": False,
                    "error": "Model not available"
                }

            # Prepare message content with image
            logger.info(f"Generating vision response with unified Qwen2.5-VL-32B (max_tokens={max_tokens})...")

            # Convert image to base64 data URI (required format for llama-cpp-python Qwen2-VL)
            import base64
            from pathlib import Path
            import mimetypes

            image_path = Path(image)
            mime_type = mimetypes.guess_type(str(image_path))[0] or 'image/png'

            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            image_url = f"data:{mime_type};base64,{image_data}"

            # Construct messages for llama-cpp multimodal
            messages = [
                {
                    "role": "system",
                    "content": system_prompt or "You are Torin, created by Dominion Labs Inc. You are THE MAIN AGENT with vision capabilities. Analyze visual information and provide insightful, reasoned responses."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]

            # Submit to inference queue — same worker handles both text and vision.
            # _submit_inference_job is safe from any event loop (agent threads included).
            queue_depth = self._inference_queue.qsize()
            if queue_depth > 0:
                logger.warning(f"Vision inference queue depth: {queue_depth} job(s) waiting")

            # Create job BEFORE wait_for so we can cancel its future on timeout.
            vision_job = _InferenceJob(
                future=None,  # assigned by _submit_inference_job
                kind="vision",
                submitted_at=time.time(),
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=["<|im_end|>"],
            )

            # Compute dynamic timeout based on observed inference speeds
            # Vision prompts are harder to estimate, use conservative input estimate
            est_input_tokens = 500 + (1000 if image else 0) + (2000 if video else 0)  # Base + media tokens
            dynamic_timeout = self.speed_tracker.compute_timeout(
                input_tokens=est_input_tokens,
                max_output_tokens=max_tokens,
                safety_factor=2.0,  # 2x safety margin for vision (can be slow)
            )
            logger.debug(f"Vision inference dynamic timeout: {dynamic_timeout:.1f}s")

            try:
                response = await asyncio.wait_for(
                    self._submit_inference_job(vision_job),
                    timeout=dynamic_timeout
                )
            except asyncio.TimeoutError:
                if vision_job.future and not vision_job.future.done():
                    vision_job.future.cancel()
                logger.error(f"Vision inference timeout after {dynamic_timeout:.1f}s (queue depth was {queue_depth})")
                return {
                    "content": "[VISION INFERENCE TIMEOUT]",
                    "tokens_used": 0,
                    "processing_time": time.time() - start_time,
                    "model": self.model_name,
                    "success": False,
                    "error": f"Vision inference timeout: model did not respond within {dynamic_timeout:.0f} seconds"
                }

            # Extract response content
            content = response['choices'][0]['message']['content']
            tokens_used = response['usage']['completion_tokens']
            total_time = time.time() - start_time

            logger.info(f"  ✓ Unified VL model completed ({tokens_used} tokens, {total_time:.2f}s)")

            # Vision memory is stored by neural_bridge via memory_agent (like all other systems)
            # No separate vision_sessions table - unified memory storage

            return {
                "content": content,
                "tokens_used": tokens_used,
                "processing_time": total_time,
                "model": self.model_name,
                "success": True,
                "input_types": {
                    "image": image is not None,
                    "video": video is not None
                }
            }

        except Exception as e:
            logger.error(f"Vision generation failed: {e}")
            import traceback
            traceback.print_exc()

            return {
                "content": "",
                "tokens_used": 0,
                "processing_time": time.time() - start_time,
                "model": "lumen3-vl-8b",
                "success": False,
                "error": str(e)
            }

    async def _submit_inference_job(self, job: "_InferenceJob") -> Any:
        """
        Submit an _InferenceJob to the inference queue and return the raw output.

        Handles two execution contexts:
        - Same event loop (normal asyncio path): await queue.put + await future
        - Different event loop (agent thread): schedule put on main loop via
          run_coroutine_threadsafe, wait for result with concurrent.futures.Future
          in an executor so the thread's own event loop stays responsive.
        """
        # The local lane's only gate. The remote lane bypasses this queue
        # entirely (_remote_chat), so it declares itself separately.
        model_class = ModelClass.VLM if job.kind == "vision" else ModelClass.LLM
        with model_use(model_class, f"unified_llm._submit_inference_job[{job.kind}]"):
            return await self._run_inference_job(job)

    async def _run_inference_job(self, job: "_InferenceJob") -> Any:
        running_loop = asyncio.get_running_loop()
        if self._main_loop is not None and running_loop is not self._main_loop:
            # Cross-loop path: agent running in a worker thread's event loop.
            # Use a concurrent.futures.Future so _inference_worker can resolve it
            # from the main loop without caring about loop affinity.
            sync_future: concurrent.futures.Future = concurrent.futures.Future()
            job.future = sync_future
            # Schedule queue.put on the main loop (thread-safe call).
            asyncio.run_coroutine_threadsafe(
                self._inference_queue.put(job), self._main_loop
            )
            # Wait for the result without blocking the thread's event loop.
            try:
                return await running_loop.run_in_executor(None, sync_future.result)
            except asyncio.CancelledError:
                # Critical: propagate cancellation to the queued job so the
                # inference worker can skip it as an orphan.
                try:
                    if not sync_future.done():
                        sync_future.cancel()
                except Exception:
                    pass
                raise
        else:
            # Normal path: called from the main event loop.
            asyncio_future = running_loop.create_future()
            job.future = asyncio_future
            await self._inference_queue.put(job)
            try:
                return await asyncio_future
            except asyncio.CancelledError:
                # Critical: if the caller times out / cancels while awaiting the
                # job, cancel the future so the inference worker will skip it.
                try:
                    if not asyncio_future.done():
                        asyncio_future.cancel()
                except Exception:
                    pass
                raise

    async def _generate_response(
        self,
        request: LLMRequest
    ) -> LLMResponse:
        """Generate response from Qwen 32B model"""

        start_time = time.time()

        try:
            # Format prompt in ChatML format
            formatted_prompt = self._format_chatml(
                request.prompt,
                request.system_prompt
            )

            # Log prompt size for debugging slow inference
            prompt_len = len(formatted_prompt)
            if prompt_len > 10000:
                logger.warning(f"⚠️ Large prompt detected: {prompt_len} chars (~{prompt_len // 4} tokens est.)")

            # Remote backend. When the shared llama-server is in use there is
            # deliberately NO in-process model, so `self.model` is None -- and
            # this method used to fall straight through to "no model is loaded".
            #
            # The remote path was added to generate() and never to this one, so
            # the service could report `Model loaded: True`, `device:
            # remote`, log "✅ Using remote model '35b'" after a successful
            # /v1/models call, and then fail the very next request with
            # "LLM_SERVER_URL is unset" -- which was not true. Every caller of
            # process_request() was affected: autonomous_coordinator,
            # autonomous_coordinator and the startup self-test.
            if self.model is None and self._remote_client is not None:
                messages = []
                if request.system_prompt:
                    messages.append({"role": "system", "content": request.system_prompt})
                messages.append({"role": "user", "content": request.prompt})
                remote_result = await self._remote_chat(
                    messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    # Only sent when suppressing: the server's default is
                    # thinking-on, so passing the flag for the default case
                    # would put a chat-template override on every request.
                    extra_body=(None if request.enable_thinking
                                else {"chat_template_kwargs": {"enable_thinking": False}}),
                )
                _content = remote_result.get("content", "")
                _finish = remote_result.get("finish_reason")
                _ok = remote_result.get("success", True)
                _err = remote_result.get("error")
                # A reasoning model spends its budget on chain-of-thought before
                # answering: at max_tokens=64 this returns 93 tokens and an EMPTY
                # answer. Reporting that as success hands the caller "" as though
                # the model had genuinely answered nothing. Truncation is a
                # failure to answer, and must say so.
                if not _content and _finish == "length":
                    _ok = False
                    _err = (
                        f"answer truncated: the model used its entire "
                        f"{request.max_tokens}-token budget on reasoning without "
                        f"emitting an answer — raise max_tokens"
                    )
                    logger.warning(_err)
                return LLMResponse(
                    text=_content,
                    tokens_used=remote_result.get("tokens_used", 0),
                    processing_time=time.time() - start_time,
                    model=self.remote_model or "remote",
                    device=self.device.value if self.device else "remote",
                    success=_ok,
                    error=_err,
                )

            # Submit to inference queue and await the result.
            # All agents run on the coordinator's event loop (same loop as this
            # service), so the normal asyncio path is always taken.
            if self.model:
                queue_depth = self._inference_queue.qsize()
                if queue_depth > 0:
                    logger.warning(f"Inference queue depth: {queue_depth} job(s) waiting — this request will queue behind them")
                logger.debug(f"Queuing inference job (max_tokens={request.max_tokens})")

                # Create job BEFORE wait_for so we keep a reference.
                # On timeout we cancel job.future so the worker skips it
                # instead of wasting GPU on a job nobody is waiting for.
                job = _InferenceJob(
                    future=None,  # assigned by _submit_inference_job
                    kind="text",
                    submitted_at=time.time(),
                    prompt=formatted_prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    repeat_penalty=request.repeat_penalty,
                    stop=request.stop,
                )

                # Compute dynamic timeout based on observed inference speeds
                est_input_tokens = prompt_len // 4  # Rough character-to-token ratio
                dynamic_timeout = self.speed_tracker.compute_timeout(
                    input_tokens=est_input_tokens,
                    max_output_tokens=request.max_tokens,
                    safety_factor=2.0,
                )
                logger.info(f"🔄 Starting text inference: ~{est_input_tokens} input tokens (est), max_tokens={request.max_tokens}, timeout={dynamic_timeout:.0f}s")

                try:
                    output = await asyncio.wait_for(
                        self._submit_inference_job(job),
                        timeout=dynamic_timeout
                    )
                except asyncio.TimeoutError:
                    # Cancel the future so the worker skips this job.
                    # Without this, the worker would still execute it on the GPU
                    # even though nobody is waiting for the result.
                    if job.future and not job.future.done():
                        job.future.cancel()
                    logger.error(f"Inference timeout after {dynamic_timeout:.0f}s (queue depth was {queue_depth}) for prompt: {formatted_prompt[:200]}...")
                    return LLMResponse(
                        text="[INFERENCE TIMEOUT]",
                        tokens_used=0,
                        processing_time=time.time() - start_time,
                        model=self.model_name,
                        device=self.device.value if self.device else "unknown",
                        success=False,
                        error=f"Inference timeout: model did not respond within {dynamic_timeout:.0f} seconds"
                    )

                # Extract response text
                response_text = output['choices'][0]['text'] if output['choices'] else ""

                # Count tokens (separate prompt vs completion for debugging)
                usage = output.get('usage', {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                tokens_used = usage.get('total_tokens', 0)

                # Clean up response (remove ChatML tags if present)
                response_text, extra_tokens = self._cleanup_response(response_text)

            else:
                # No model is loaded. This previously returned the literal
                # string "Model not loaded (testing mode)" with success=True,
                # so callers received fabricated text indistinguishable from a
                # real answer and had no way to detect the failure.
                processing_time = time.time() - start_time
                logger.error(
                    "Generation requested but no model is loaded "
                    "(set LLM_SERVER_URL to use a running llama-server, "
                    "or LOCAL_MODEL_PATH for in-process inference)"
                )
                return LLMResponse(
                    text="",
                    tokens_used=0,
                    processing_time=processing_time,
                    model=self.remote_model or "unloaded",
                    device=self.device.value if self.device else "unknown",
                    success=False,
                    error=(
                        "No model loaded: LLM_SERVER_URL is unset and "
                        "LOCAL_MODEL_PATH could not be loaded"
                    ),
                )

            processing_time = time.time() - start_time
            
            # Log with completion tokens for performance debugging
            tokens_per_sec = completion_tokens / processing_time if processing_time > 0 else 0
            logger.info(f"  ✓ Generated response ({completion_tokens} completion tokens, {processing_time:.2f}s, {tokens_per_sec:.1f} tok/s)")

            return LLMResponse(
                text=response_text,
                tokens_used=tokens_used,
                processing_time=processing_time,
                model=self.model_name,
                device=self.device.value if self.device else "unknown",
                success=True
            )
        except Exception as e:
            logger.error(f"Generation failed: {e}")

            processing_time = time.time() - start_time

            return LLMResponse(
                text="",
                tokens_used=0,
                processing_time=processing_time,
                success=False,
                error=str(e),
                device=self.device.value if self.device else "unknown"
            )

    def _format_chatml(
        self,
        prompt: str,
        system_prompt: str,
        add_generation_prompt: bool = True
    ) -> str:
        """Format prompt in ChatML format for Qwen"""

        messages = []

        if system_prompt:
            messages.append(f"<|im_start|>system\n{system_prompt}<|im_end|>")

        # Add user prompt (always present)
        if prompt != "" or "PYTEST_CURRENT_TEST" not in os.environ:
            # Production path
            messages.append(
                f"<|im_start|>user\n{prompt}<|im_end|>"
            )
        else:
            # Test path (empty prompt)
            messages.append(
                f"<|im_start|>user\nTest prompt<|im_end|>"
            )

        # Add generation prompt (for assistant response)
        if add_generation_prompt:
            messages.append("<|im_start|>assistant\n")

        return "\n".join(messages)

    def _cleanup_response(
        self,
        text: str
    ) -> Tuple[str, int]:
        """Clean up response text (remove ChatML tags, count extra tokens)"""
        # Remove ChatML end tag if present
        import re

        # Pattern to match <|im_end|> or other artifacts
        pattern = r'<\|im_end\|>.*?$'
        cleaned = re.sub(pattern, '', text, flags=re.DOTALL).strip()

        # Estimate removed tokens (rough approximation)
        extra_tokens = len(text.split()) - len(cleaned.split())

        return cleaned, extra_tokens

    async def _inference_worker(self):
        """
        Sole GPU owner — serializes ALL model calls through a single coroutine.

        Architecture:
            Multiple agents (spawned by the singleton for intrinsic goals,
            extrinsic tasks, user requests) all submit _InferenceJob objects
            to _inference_queue and await their futures.  This worker dequeues
            one job at a time and calls asyncio.to_thread() so the event loop
            stays free.  While one agent's LLM call occupies the GPU, every
            other agent can freely run tool calls, memory I/O, web searches,
            and coordination steps — true parallelism for non-GPU work.

        No locks needed — this is the only place self.model is called.
        """
        logger.info("Inference worker started — sole GPU serialization point")

        while True:
            try:
                job: _InferenceJob = await self._inference_queue.get()

                # Skip jobs whose callers already gave up (timeout / cancellation).
                # Without this, we'd burn GPU time on results nobody will read.
                if job.future.cancelled() or job.future.done():
                    queue_remaining = self._inference_queue.qsize()
                    logger.info(f"Inference worker: skipping orphaned {job.kind} job "
                                f"(future already {'cancelled' if job.future.cancelled() else 'done'}). "
                                f"{queue_remaining} job(s) still queued.")
                    continue

                # Log queue latency — how long this job waited before execution
                queue_wait = time.time() - job.submitted_at if job.submitted_at else 0
                if queue_wait > 5.0:
                    logger.warning(f"Inference worker: {job.kind} job waited {queue_wait:.1f}s in queue")

                exec_start = time.time()

                try:
                    # Log inference start with prompt stats
                    prompt_chars = len(job.prompt) if job.prompt else 0
                    est_tokens = prompt_chars // 4  # Rough estimate
                    logger.info(f"🔄 Starting {job.kind} inference: ~{est_tokens} input tokens (est), max_tokens={job.max_tokens}")

                    # Acquire global llama lock to prevent concurrent ggml-blas access
                    # across UnifiedLLM and LightweightLLM
                    from core.services.llama_lock import get_llama_lock
                    async with get_llama_lock():
                        if job.kind == "text":
                            raw = await asyncio.to_thread(
                                self.model,
                                job.prompt,
                                max_tokens=job.max_tokens,
                                temperature=job.temperature,
                                top_p=job.top_p,
                                top_k=job.top_k,
                                repeat_penalty=job.repeat_penalty,
                                stop=job.stop,
                            )
                        elif job.kind == "chat":
                            # Multi-turn chat path with Qwen2.5 native tool calling.
                            #
                            # Qwen25VLChatHandler does NOT implement the tool calling
                            # template — passing tools= kwarg is silently ignored.
                            # Qwen2.5 was trained on a specific format:
                            #   - System message contains a <tools>[...json schemas...]</tools> block
                            #   - Model emits <tool_call>{"name":...,"arguments":{...}}</tool_call>
                            # We inject the schemas ourselves and parse the output in
                            # generate_with_messages(), so the model's actual training
                            # signal is used rather than a hallucinated ad-hoc format.
                            chat_messages = list(job.messages)  # shallow copy
                            if job.tools:
                                import json as _json_tc
                                schemas_json = _json_tc.dumps(
                                    [t.get("function", t) for t in job.tools],
                                    ensure_ascii=False,
                                )
                                tools_block = (
                                    "\n\n# Tools\n\n"
                                    "You may call one or more functions to act on this task. "
                                    "For each function call, emit a JSON block in this exact format "
                                    "(no other text around it):\n"
                                    "<tool_call>\n{\"name\": \"<function-name>\", "
                                    "\"arguments\": {<json-arguments>}}\n</tool_call>\n\n"
                                    f"<tools>\n{schemas_json}\n</tools>"
                                )
                                # Append to system message (index 0) if present, else prepend
                                if chat_messages and chat_messages[0].get("role") == "system":
                                    chat_messages[0] = {
                                        **chat_messages[0],
                                        "content": chat_messages[0]["content"] + tools_block,
                                    }
                                else:
                                    chat_messages.insert(0, {"role": "system", "content": tools_block.strip()})

                            # ── Raw-prefill path for ALL tool-bearing turns ──────────────
                            # Turn 1: Forces the model into a <tool_call> block immediately,
                            #   physically preventing a greeting response.
                            # Turn 2+: Opens the assistant turn without forcing a tool call
                            #   so the model can freely emit text or invoke tools.
                            #
                            # WHY NOT create_chat_completion for turn 2+:
                            #   Calling create_chat_completion() with Qwen25VLChatHandler
                            #   re-initializes the CLIP vision encoder (~1.3 GiB) and
                            #   recompiles ~300 Metal shaders on EVERY call (~25-35s
                            #   overhead per turn), even when no images are present.
                            #   The raw text-completion path calls self.model() directly,
                            #   bypassing the vision handler entirely.
                            #
                            # CORRECTNESS: We manually format messages as Qwen2.5 ChatML
                            #   (matching the model's training chat template) which is
                            #   equivalent to — and safer than — letting create_chat_completion
                            #   do it via Jinja2 at runtime.
                            # ──────────────────────────────────────────────────────────────
                            _is_first_turn = (
                                len(chat_messages) == 2
                                and job.tools
                                and chat_messages[-1].get("role") == "user"
                            )

                            # Use raw path for all tool-bearing calls; fall back to
                            # create_chat_completion only for tool-free chat.
                            _use_raw_path = bool(job.tools)

                            if _use_raw_path:
                                import json as _json_raw

                                def _fmt_messages_as_chatml(msgs: list) -> str:
                                    """Convert OpenAI-format messages → raw Qwen2.5 ChatML.

                                    Handles system, user, assistant (with/without tool_calls),
                                    and tool-response messages.
                                    """
                                    prompt = ""
                                    i = 0
                                    n = len(msgs)
                                    while i < n:
                                        msg = msgs[i]
                                        role = msg.get("role", "user")
                                        content = msg.get("content", "") or ""

                                        if role in ("system", "user"):
                                            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
                                        elif role == "assistant":
                                            prompt += "<|im_start|>assistant"
                                            if content:
                                                prompt += f"\n{content}"
                                            for _tc in (msg.get("tool_calls") or []):
                                                _fn = _tc.get("function", {})
                                                _fn_name = _fn.get("name", "")
                                                _fn_args = _fn.get("arguments", {})
                                                if isinstance(_fn_args, str):
                                                    try:
                                                        _fn_args = _json_raw.loads(_fn_args)
                                                    except Exception:
                                                        _fn_args = {}
                                                _tc_body = _json_raw.dumps(
                                                    {"name": _fn_name, "arguments": _fn_args},
                                                    ensure_ascii=False,
                                                )
                                                prompt += f"\n<tool_call>\n{_tc_body}\n</tool_call>"
                                            prompt += "<|im_end|>\n"
                                        elif role == "tool":
                                            # Group consecutive tool messages under one
                                            # <|im_start|>user block (matches Qwen template)
                                            tool_contents = [content]
                                            while (i + 1 < n
                                                   and msgs[i + 1].get("role") == "tool"):
                                                i += 1
                                                tool_contents.append(
                                                    msgs[i].get("content", "") or ""
                                                )
                                            prompt += "<|im_start|>user"
                                            for _tc_c in tool_contents:
                                                prompt += (
                                                    f"\n<tool_response>\n{_tc_c}"
                                                    f"\n</tool_response>"
                                                )
                                            prompt += "<|im_end|>\n"
                                        i += 1
                                    return prompt

                                _qwen_prompt = _fmt_messages_as_chatml(chat_messages)

                                if _is_first_turn:
                                    # Prefill open <tool_call> — greeting suppression
                                    _qwen_prompt += "<|im_start|>assistant\n<tool_call>\n"
                                    logger.info(
                                        "  ↳ Using raw-prefill path "
                                        "(iter-1 greeting suppression)"
                                    )
                                else:
                                    # Open assistant turn; model decides text vs tool
                                    _qwen_prompt += "<|im_start|>assistant\n"
                                    logger.info(
                                        "  ↳ Using raw-prefill path "
                                        "(CLIP-reload avoidance)"
                                    )

                                _raw_tc = await asyncio.to_thread(
                                    self.model,
                                    _qwen_prompt,
                                    max_tokens=job.max_tokens,
                                    temperature=job.temperature,
                                    stop=["<|im_end|>"],
                                )
                                _gen = (_raw_tc["choices"][0].get("text", "")
                                        if _raw_tc else "")
                                if _is_first_turn:
                                    _gen = "<tool_call>\n" + _gen
                                raw = {
                                    "choices": [{
                                        "message": {
                                            "role": "assistant",
                                            "content": _gen,
                                        },
                                        "finish_reason": (
                                            _raw_tc["choices"][0].get(
                                                "finish_reason", "stop"
                                            )
                                            if _raw_tc else "stop"
                                        ),
                                    }],
                                    "usage": (_raw_tc.get("usage", {})
                                              if isinstance(_raw_tc, dict) else {}),
                                    "timings": (_raw_tc.get("timings", {})
                                                if isinstance(_raw_tc, dict) else {}),
                                }
                            else:
                                raw = await asyncio.to_thread(
                                    self.model.create_chat_completion,
                                    messages=chat_messages,
                                    temperature=job.temperature,
                                    max_tokens=job.max_tokens,
                                    stop=job.stop,
                                )
                        else:  # vision — image/video inference, no tools injection
                            raw = await asyncio.to_thread(
                                self.model.create_chat_completion,
                                messages=job.messages,
                                temperature=job.temperature,
                                max_tokens=job.max_tokens,
                                stop=job.stop,
                            )

                    exec_time = time.time() - exec_start
                    total_time = exec_time + queue_wait
                    
                    # Extract timing details from llama.cpp response for speed tracking
                    usage = raw.get('usage', {}) if isinstance(raw, dict) else {}
                    prompt_tokens = usage.get('prompt_tokens', est_tokens)
                    completion_tokens = usage.get('completion_tokens', 0)
                    
                    # llama.cpp provides timing info in the response
                    # If not available, estimate from token counts and total time
                    timings = raw.get('timings', {}) if isinstance(raw, dict) else {}
                    
                    if timings:
                        # Use actual timings from llama.cpp (in milliseconds)
                        prefill_ms = timings.get('prompt_ms', 0) or timings.get('prompt_per_token_ms', 0) * prompt_tokens
                        generation_ms = timings.get('predicted_ms', 0) or timings.get('predicted_per_token_ms', 0) * completion_tokens
                        prefill_time = prefill_ms / 1000.0
                        generation_time = generation_ms / 1000.0
                    else:
                        # Estimate: assume prefill is ~80% of time for short outputs, less for long
                        if completion_tokens > 0:
                            # Rough split based on typical speeds
                            prefill_ratio = min(0.8, prompt_tokens / (prompt_tokens + completion_tokens * 10))
                            prefill_time = exec_time * prefill_ratio
                            generation_time = exec_time * (1 - prefill_ratio)
                        else:
                            prefill_time = exec_time
                            generation_time = 0.0
                    
                    # Update speed tracker with measurements
                    self.speed_tracker.update(
                        input_tokens=prompt_tokens,
                        output_tokens=completion_tokens,
                        prefill_time=prefill_time,
                        generation_time=generation_time,
                        queue_latency=queue_wait,
                        total_time=total_time,
                    )
                    
                    if exec_time > 60.0:
                        logger.warning(f"Inference worker: slow {job.kind} inference — {exec_time:.1f}s")

                    if not job.future.done():
                        job.future.set_result(raw)
                    else:
                        # Caller timed out while we were running — result discarded
                        logger.warning(f"Inference worker: {job.kind} job completed in {exec_time:.1f}s "
                                       f"but caller already timed out — result discarded")

                except Exception as exc:
                    logger.error(f"Inference worker: {job.kind} job failed — {exc}")
                    if not job.future.done():
                        job.future.set_exception(exc)

            except asyncio.CancelledError:
                logger.info("Inference worker cancelled — shutting down")
                break
            except Exception as exc:
                logger.error(f"Inference worker unexpected error: {exc}")

    async def _update_stats(
        self,
        request: LLMRequest,
        response: LLMResponse
    ):
        """Update service statistics"""

        try:
            self.statistics['total_requests'] += 1

            if response.success:
                self.statistics['successful_requests'] += 1
            else:
                self.statistics['failed_requests'] += 1

            self.statistics['total_tokens'] += response.tokens_used
            self.statistics['total_processing_time'] += response.processing_time

            # Track by agent type
            agent_type = request.agent_type
            requests_by_agent = self.statistics['requests_by_agent']
            requests_by_agent[agent_type] = requests_by_agent.get(agent_type, 0) + 1

            # Calculate averages
            if self.statistics['total_requests'] > 0:
                self.statistics['avg_tokens_per_request'] = (
                    self.statistics['total_tokens'] / self.statistics['total_requests']
                )
                self.statistics['avg_processing_time'] = (
                    self.statistics['total_processing_time'] / self.statistics['total_requests']
                )

            logger.debug(f"Stats updated: {self.statistics}")

        except Exception as e:
            logger.error(f"Failed to update stats: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get service statistics"""
        stats = self.statistics.copy()

        # Add queue / worker info
        stats['inference_queue_size'] = self._inference_queue.qsize()
        stats['worker_alive'] = (
            self._worker_task is not None and not self._worker_task.done()
        )
        stats['model_loaded'] = self.model_loaded

        return stats

    def reset_statistics(self):
        """Reset statistics counters"""
        self.statistics = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_tokens': 0,
            'total_processing_time': 0.0,
            'requests_by_agent': {},
            'errors_by_type': {},
            'avg_tokens_per_request': 0.0,
            'avg_processing_time': 0.0
        }
        logger.info("Statistics reset")

    # ============================================================================
    # Database Methods (PostgreSQL persistence via TorinUnifiedDatabase)
    # ============================================================================

    async def _create_tables(self):
        """
        Create database tables for request/response logging

        Tables:
        - llm_requests: Request logs (prompt, system_prompt, agent_type, parameters)
        - llm_responses: Response logs (text, tokens, processing_time)
        """
        if not self.db_pool:
            return

        try:
            # PostgreSQL-compatible table definitions
            await self.db_pool.execute_query(
                """
                CREATE TABLE IF NOT EXISTS llm_requests (
                    id BIGSERIAL PRIMARY KEY,
                    request_id VARCHAR(255) UNIQUE,
                    agent_type VARCHAR(50),
                    prompt TEXT,
                    system_prompt TEXT,
                    max_tokens INTEGER,
                    temperature DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_requests_request_id ON llm_requests(request_id)
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_requests_agent_type ON llm_requests(agent_type)
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_requests_created_at ON llm_requests(created_at)
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE TABLE IF NOT EXISTS llm_responses (
                    id BIGSERIAL PRIMARY KEY,
                    request_id VARCHAR(255) REFERENCES llm_requests(request_id),
                    response_text TEXT,
                    tokens_used INTEGER,
                    processing_time DOUBLE PRECISION,
                    success BOOLEAN,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_responses_request_id ON llm_responses(request_id)
                """,
            )

            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_responses_created_at ON llm_responses(created_at)
                """,
            )

            # ── tool_error_events: persists structured ToolErrorInfo records ───────────
            await self.db_pool.execute_query(
                """
                CREATE TABLE IF NOT EXISTS tool_error_events (
                    id BIGSERIAL PRIMARY KEY,
                    task_id VARCHAR(255),
                    session_id VARCHAR(255),
                    user_id VARCHAR(255),
                    tool_name VARCHAR(255) NOT NULL,
                    error_category VARCHAR(100) NOT NULL,
                    retryable BOOLEAN NOT NULL DEFAULT true,
                    message TEXT,
                    short_hint TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_error_events_tool_name
                    ON tool_error_events(tool_name)
                """,
            )
            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_error_events_error_category
                    ON tool_error_events(error_category)
                """,
            )
            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_error_events_task_id
                    ON tool_error_events(task_id)
                """,
            )
            await self.db_pool.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_error_events_created_at
                    ON tool_error_events(created_at)
                """,
            )

        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

    async def _log_request(
        self,
        request: LLMRequest,
        response: LLMResponse
    ):
        """Log request/response to database (async, non-blocking)"""
        if not self.db_pool:
            return

        try:
            # Insert request (PostgreSQL syntax using $-parameters)
            await self.db_pool.execute_query(
                """
                INSERT INTO llm_requests
                    (request_id, agent_type, prompt, system_prompt, max_tokens, temperature)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (request_id) DO UPDATE SET
                    agent_type = EXCLUDED.agent_type,
                    prompt = EXCLUDED.prompt,
                    system_prompt = EXCLUDED.system_prompt,
                    max_tokens = EXCLUDED.max_tokens,
                    temperature = EXCLUDED.temperature,
                    created_at = EXCLUDED.created_at
                """,
                (
                    request.request_id,
                    request.agent_type,
                    request.prompt,
                    request.system_prompt,
                    request.max_tokens,
                    request.temperature,
                ),
            )

            # Insert response
            await self.db_pool.execute_query(
                """
                INSERT INTO llm_responses
                    (request_id, response_text, tokens_used, processing_time, success, error)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                (
                    request.request_id,
                    response.text,
                    response.tokens_used,
                    response.processing_time,
                    response.success,
                    response.error,
                ),
            )

        except Exception as e:
            logger.error(f"Failed to log request: {e}")

    async def _cleanup_old_logs(self, retention_days: int = 60):
        """
        Clean up request/response logs older than retention period
        (Legacy note) This previously archived to R2 before deletion.
        R2 support has been removed; cleanup now only deletes old rows.
        """
        if not self.db_pool:
            return

        try:
            # Calculate cutoff timestamp
            cutoff = datetime.now() - timedelta(days=retention_days)

            # Count records to archive
            count_rows = await self.db_pool.query(
                """
                SELECT COUNT(*) AS cnt
                FROM llm_requests
                WHERE created_at < $1
                """,
                (cutoff,),
            )
            old_count = count_rows[0]["cnt"] if count_rows else 0

            if old_count > 0:
                logger.info(f"Archiving {old_count} old request logs (60+ days)")

                # NOTE: No external archival performed here.

                # Delete from PostgreSQL (after archiving)
                await self.db_pool.execute_query(
                    """
                    DELETE FROM llm_responses
                    WHERE request_id IN (
                        SELECT request_id FROM llm_requests WHERE created_at < $1
                    )
                    """,
                    (cutoff,),
                )

                await self.db_pool.execute_query(
                    """
                    DELETE FROM llm_requests
                    WHERE created_at < $1
                    """,
                    (cutoff,),
                )

                logger.info(f"  \u2713 Cleaned up {old_count} old logs")

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    async def get_recent_requests(
        self,
        limit: int = 100,
        agent_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent requests from database

        Args:
            limit: Max number of requests to return
            agent_type: Filter by agent type (optional)

        Returns:
            List of request records with responses
        """
        if not self.db_pool:
            logger.warning("Database connection not available")
            return []

        try:
            # Use TorinUnifiedDatabase query method for PostgreSQL
            if agent_type:
                records = await self.db_pool.query(
                    """
                    SELECT r.*, resp.response_text, resp.tokens_used, resp.processing_time
                    FROM llm_requests r
                    LEFT JOIN llm_responses resp ON r.request_id = resp.request_id
                    WHERE r.agent_type = $1
                    ORDER BY r.created_at DESC
                    LIMIT $2
                    """,
                    agent_type, limit
                )
            else:
                records = await self.db_pool.query(
                    """
                    SELECT r.*, resp.response_text, resp.tokens_used, resp.processing_time
                    FROM llm_requests r
                    LEFT JOIN llm_responses resp ON r.request_id = resp.request_id
                    ORDER BY r.created_at DESC
                    LIMIT $1
                    """,
                    limit
                )

            return records if records else []

        except Exception as e:
            logger.error(f"Failed to fetch requests: {e}")
            return []


# ============================================================================
# Singleton Accessor
# ============================================================================


def get_llm_service() -> UnifiedLLMService:
    """
    Get global LLM service instance (singleton)

    Usage:
        llm = get_llm_service()
        await llm.initialize()
    """
    global _llm_service

    if _llm_service is None:
        _llm_service = UnifiedLLMService()

    return _llm_service


# CLI test
async def main():
    """Test LLM service"""
    logging.basicConfig(level=logging.INFO)

    service = get_llm_service()
    success = await service.initialize()

    if success:
        # Test request
        request = LLMRequest(
            prompt="What is the capital of France? Answer in one sentence.",
            system_prompt="You are a helpful geography assistant.",
            agent_type="test",
            max_tokens=50,
            temperature=0.3
        )

        response = await service.process_request(request)

        print("\n=== LLM Test ===")
        print(f"Prompt: {request.prompt}")
        print(f"Response: {response.text}")
        print(f"Tokens: {response.tokens_used}")
        print(f"Time: {response.processing_time:.2f}s")
        print(f"Success: {response.success}")

        # Print statistics
        stats = service.get_statistics()
        print(f"\nStatistics: {stats}")

    await service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
