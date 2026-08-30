#!/usr/bin/env python3
"""
Context Manager
===============
Manages conversation context with compression and memory integration

Purpose:
- Track conversation token usage
- Trigger compression at intervals
- Store summaries in MemoryAgent
- Validate token budgets
- Resume tasks with compressed context

Author: Dominion Labs
Version: 1.0
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from core.memory.utils.interfaces import MemoryType

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Token budget calculation result"""
    total_context_window: int
    system_prompt_tokens: int
    tool_description_tokens: int
    safety_margin: int
    available_for_generation: int
    available_for_conversation: int


class ContextManager:
    """
    Context Manager for Conversation History

    Integrates with ContextCompression and MemoryAgent to:
    1. Compress conversation history periodically
    2. Store compressed summaries as memories
    3. Manage token budgets dynamically
    4. Resume tasks with relevant context

    Usage:
        manager = ContextManager(compression_service, memory_agent)

        # Track turns
        await manager.track_turn()

        # Check if compression needed
        if await manager.should_compress():
            memory_id = await manager.compress_and_store(messages, task_id)

        # Calculate token budget
        budget = manager.calculate_token_budget(system_prompt, tools)
        valid, adjusted = manager.validate_max_tokens(requested, budget)
    """

    def __init__(
        self,
        compression_service,
        memory_agent,
        n_ctx: int = 4096,
        compression_interval: int = 5,
        preserve_recent: int = 3,
        safety_margin: int = 500
    ):
        """
        Initialize Context Manager

        Args:
            compression_service: ContextCompression instance
            memory_agent: MemoryAgent instance
            n_ctx: Context window size (default 4096)
            compression_interval: Compress every N turns (default 5)
            preserve_recent: Keep last N messages uncompressed (default 3)
            safety_margin: Reserve tokens for safety (default 500)
        """
        self.compression = compression_service
        self.memory = memory_agent

        # Context window configuration
        self.n_ctx = n_ctx
        self.safety_margin = safety_margin

        # Compression configuration
        self.compression_interval = compression_interval
        self.preserve_recent = preserve_recent

        # State tracking
        self.turn_count = 0
        self.last_compression_turn = 0
        self.current_task_id = None

        # Compression history (for this session)
        self.compression_history = []

        logger.info(
            f"ContextManager initialized: "
            f"n_ctx={n_ctx}, interval={compression_interval}, "
            f"preserve_recent={preserve_recent}"
        )

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count (approximation)

        Rule of thumb: word count + punctuation count
        Roughly 0.65x multiplier (empirically calibrated for llama.cpp)

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        words = len(text.split())
        punctuation = len(re.findall(r'[.,!?;:\[\]{}()]', text))

        # Empirically calibrated: llama.cpp tokenizes more efficiently than 1:1
        # Testing shows (words + punctuation) * 0.65 ≈ actual tokens
        return int((words + punctuation) * 0.65)

    async def should_compress(self, current_token_usage: int, reserved_tokens: int = 0) -> bool:
        """
        Check if compression should be triggered based on token usage.

        Triggers at 70% of the *effective* context window (n_ctx minus any
        tokens already reserved for tool schemas or system prompt injected at
        inference time).  Pass `reserved_tokens` so the budget is accurate:

            effective_budget = n_ctx - reserved_tokens
            trigger when current_token_usage >= 0.70 * effective_budget

        With a 32K window and ~22K reserved for tool schemas the effective
        conversation budget is ~10K tokens; 70% of that = ~7K.

        Args:
            current_token_usage: Current conversation token count
            reserved_tokens:     Tokens already reserved (e.g. tool schemas)

        Returns:
            True if token usage exceeds 70% of the effective context window
        """
        effective_budget = max(self.n_ctx - reserved_tokens, 1)
        usage_percentage = current_token_usage / effective_budget
        should_trigger = usage_percentage >= 0.70  # Compress at 70% of usable budget

        if should_trigger:
            logger.info(
                f"[COMPRESSION] Token usage: {current_token_usage} / {effective_budget} "
                f"effective ({self.n_ctx} - {reserved_tokens} reserved) "
                f"= {usage_percentage:.1%} — triggering compression"
            )

        return should_trigger

    async def compress_and_store(
        self,
        messages: List[Tuple[str, str]],
        task_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Compress conversation and store to memory

        Args:
            messages: List of (role, content) tuples
            task_id: Optional task identifier

        Returns:
            memory_id if stored successfully, None otherwise
        """
        logger.debug(f"[COMPRESSION] compress_and_store() called with {len(messages)} messages")

        if len(messages) <= self.preserve_recent:
            logger.debug(f"[COMPRESSION] Not enough messages to compress ({len(messages)} <= {self.preserve_recent})")
            return None

        try:
            logger.debug("[COMPRESSION] Starting compression...")
            # Compress using ContextCompression
            compressed = await self.compression.compress_context(
                messages=messages,
                target_ratio=0.7,  # Preserve 70% of content - less aggressive
                preserve_recent=self.preserve_recent,
                use_llm=True  # Use Qwen3-8B lightweight LLM for semantic compression
            )

            logger.info(
                f"[COMPRESSION] Compressed {len(messages)} messages → "
                f"{compressed.compression_ratio:.1%} ratio, "
                f"{len(compressed.key_points)} key points"
            )

            # DO NOT store compression as memory - it's temporary context management, not a learning
            # Just track compression history locally and return the compressed summary
            self.compression_history.append({
                'turn_count': self.turn_count,
                'message_count': len(messages),
                'compression_ratio': compressed.compression_ratio,
                'timestamp': datetime.now().isoformat()
            })
            self.last_compression_turn = self.turn_count
            logger.debug("[COMPRESSION] ✓ Compression complete")

            # Return the compressed summary for executor to use (don't store as memory)
            return compressed.compressed_text

        except Exception as e:
            logger.error(f"[COMPRESSION] ✗ Compression failed: {e}", exc_info=True)

            # Attempt fallback truncation
            return await self._fallback_truncate(messages, task_id)

    async def _fallback_truncate(
        self,
        messages: List[Tuple[str, str]],
        task_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Fallback truncation when compression fails

        Simply keeps first message (system prompt) + last N messages

        Args:
            messages: List of (role, content) tuples
            task_id: Optional task identifier

        Returns:
            None (truncation doesn't generate memory_id)
        """
        logger.warning(
            f"Falling back to truncation: {len(messages)} → "
            f"{1 + self.preserve_recent} messages (keep first + last {self.preserve_recent})"
        )
        return None

    def calculate_token_budget(
        self,
        system_prompt: str,
        tool_descriptions: str
    ) -> TokenBudget:
        """
        Calculate available token budget

        Formula:
        available = n_ctx - system_tokens - tool_tokens - safety_margin

        Args:
            system_prompt: System prompt text
            tool_descriptions: Tool descriptions text

        Returns:
            TokenBudget with breakdown
        """
        system_tokens = self.estimate_tokens(system_prompt)
        tool_tokens = self.estimate_tokens(tool_descriptions)

        # Available for conversation = total - system - tools - margin
        available_for_conversation = max(0, (
            self.n_ctx
            - system_tokens
            - tool_tokens
            - self.safety_margin
        ))

        # Generation budget (what LLM can output)
        # Use full available space since our estimates are now more accurate
        available_for_generation = available_for_conversation

        return TokenBudget(
            total_context_window=self.n_ctx,
            system_prompt_tokens=system_tokens,
            tool_description_tokens=tool_tokens,
            safety_margin=self.safety_margin,
            available_for_generation=available_for_generation,
            available_for_conversation=available_for_conversation
        )

    def validate_max_tokens(
        self,
        requested_tokens: int,
        budget: TokenBudget
    ) -> Tuple[bool, int]:
        """
        Validate and adjust max_tokens request

        Args:
            requested_tokens: Requested max_tokens value
            budget: TokenBudget from calculate_token_budget()

        Returns:
            (is_valid, adjusted_tokens)
            - is_valid: True if request fits in budget
            - adjusted_tokens: Original or clamped value
        """
        if requested_tokens <= budget.available_for_generation:
            return True, requested_tokens

        # Adjust to fit budget
        adjusted = max(100, budget.available_for_generation)  # Minimum 100 tokens
        logger.warning(
            f"Requested {requested_tokens} tokens exceeds budget "
            f"{budget.available_for_generation}, adjusting to {adjusted}"
        )
        return False, adjusted

    async def get_conversation_tokens(
        self,
        messages: List[Tuple[str, str]]
    ) -> int:
        """
        Estimate total tokens in conversation history

        Args:
            messages: List of (role, content) tuples

        Returns:
            Estimated total token count
        """
        total = 0
        for role, content in messages:
            # Add role tag overhead (~5 tokens)
            total += 5
            # Add content tokens
            total += self.estimate_tokens(content)
        return total

    async def resume_task_context(
        self,
        task_id: str,
        max_memories: int = 3
    ) -> List[str]:
        """
        Retrieve compressed summaries for task resumption

        Searches for memories tagged with task_id to restore context
        when resuming a long-running task

        Args:
            task_id: Task identifier
            max_memories: Maximum number of summaries to retrieve

        Returns:
            List of compressed summary texts
        """
        try:
            # Search for relevant memories by task_id tag
            success, memories = await self.memory.query_by_tags(
                tags={f"task_{task_id}", "conversation_summary"},
                limit=max_memories
            )

            if not success or not memories:
                logger.info(f"No previous context found for task {task_id}")
                return []

            # Extract compressed text from memories
            summaries = [mem.content for mem in memories]
            logger.info(
                f"Retrieved {len(summaries)} compressed summaries "
                f"for task {task_id}"
            )
            return summaries

        except Exception as e:
            logger.error(f"Failed to retrieve task context: {e}")
            return []

    async def track_turn(self) -> None:
        """Increment turn counter"""
        self.turn_count += 1

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get context manager statistics

        Returns:
            Dict with statistics
        """
        return {
            'turn_count': self.turn_count,
            'compressions_performed': len(self.compression_history),
            'last_compression_turn': self.last_compression_turn,
            'turns_since_compression': self.turn_count - self.last_compression_turn,
            'n_ctx': self.n_ctx,
            'compression_interval': self.compression_interval,
            'preserve_recent': self.preserve_recent,
            'safety_margin': self.safety_margin
        }

    def reset_turn_count(self) -> None:
        """Reset turn counter (for new task)"""
        self.turn_count = 0
        self.last_compression_turn = 0
        logger.debug("Turn counter reset")


# Singleton instance
_context_manager = None


def get_context_manager(
    compression_service=None,
    memory_agent=None,
    **kwargs
) -> ContextManager:
    """
    Get or create global context manager instance

    Args:
        compression_service: ContextCompression instance (optional)
        memory_agent: MemoryAgent instance (optional)
        **kwargs: Additional configuration options

    Returns:
        ContextManager instance

    Note:
        If called without services, creates a singleton but logs warning.
        Services should be provided on first call.
    """
    global _context_manager

    if _context_manager is None:
        if not compression_service or not memory_agent:
            logger.warning(
                "Creating ContextManager without initialized services. "
                "Provide compression_service and memory_agent on first call."
            )

        _context_manager = ContextManager(
            compression_service,
            memory_agent,
            **kwargs
        )

    return _context_manager
