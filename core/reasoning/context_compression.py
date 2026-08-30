#!/usr/bin/env python3
"""
Context Compression
==========================
Compress conversation context to reduce token usage while preserving information

Purpose:
- Compress long conversation histories
- Extract key information from context
- Remove redundancy and noise
- Preserve critical details for reasoning

Techniques:
- Semantic summarization (LLM-based)
- Redundancy removal (deduplication)
- Key point extraction (importance scoring)
- Progressive compression (multi-level)
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CompressedContext:
    """Compressed conversation context"""
    original_messages: List[Tuple[str, str]]  # (role, content)
    compressed_text: str
    key_points: List[str]
    compression_ratio: float  # original_length / compressed_length
    metadata: Dict[str, Any] = field(default_factory=dict)
    original_length: int = 0  # Character count
    compressed_length: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class ContextCompression:
    """
    Context Compression System

    Purpose:
    - Compress conversation context intelligently
    - Preserve critical information while reducing tokens
    """

    def __init__(self):
        self.stats = {
            'total_compressions': 0,
            'total_chars_saved': 0,
            'avg_compression_ratio': 0.0
        }

        logger.info("ContextCompression initialized")

    def _count_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)"""
        return len(text.split()) + len(re.findall(r'[.,!?;:]', text))

    async def compress_context(
        self,
        messages: List[Tuple[str, str]],
        target_ratio: float,
        preserve_recent: int = 3,
        use_llm: bool = True
    ) -> CompressedContext:
        """
        Compress conversation context

        Args:
            messages: List of (role, content) tuples
            target_ratio: Target compression ratio (0-1, e.g., 0.5 = 50% size)
            preserve_recent: Number of recent messages to keep uncompressed
            use_llm: Whether to use LLM for semantic summarization

        Returns:
            CompressedContext with compressed text and metadata
        """
        start_time = datetime.now()

        logger.info(
            f"Compressing context: {len(messages)} messages → target {target_ratio:.0%} "
            f"(preserving {preserve_recent} recent)"
        )

        # Separate messages into compressible and preserved
        compressible = messages[:-preserve_recent] if len(messages) > preserve_recent else []
        preserved = messages[-preserve_recent:] if len(messages) > preserve_recent else messages
        recent_only = messages[-preserve_recent:] if preserve_recent > 0 else []

        if not compressible:
            # Nothing to compress
            return CompressedContext(
                original_messages=messages,
                compressed_text=self._format_messages(messages),
                key_points=[],
                compression_ratio=1.0,
                metadata={'strategy': 'no_compression_needed'},
                original_length=0
            )

        # Calculate lengths
        original_text = self._format_messages(compressible)
        original_length = len(original_text)

        # Extract key points from older messages
        key_points = await self._extract_key_points(compressible, target_ratio)

        # Compress based on strategy
        if use_llm:
            # Use LLM to create semantic summary
            compressed = await self._llm_compress(compressible, key_points)
            strategy = "llm_summarization"

        else:
            # Use rule-based compression
            compressed = await self._rule_based_compress(compressible)
            strategy = "rule_based"

        # Combine compressed older context + recent messages
        full_compressed = compressed + "\n\n" + self._format_messages(recent_only)
        compressed_length = len(full_compressed)

        # Calculate ratio
        actual_ratio = compressed_length / original_length if original_length > 0 else 1.0
        chars_saved = original_length - compressed_length

        # Update statistics
        self.stats['total_compressions'] += 1
        self.stats['total_chars_saved'] += chars_saved

        avg_count = self.stats['total_compressions']
        prev_avg = self.stats['avg_compression_ratio']
        self.stats['avg_compression_ratio'] = (
            (prev_avg * (avg_count - 1) + actual_ratio) / avg_count
        )

        logger.info(
            f"✓ Compressed {len(messages)} → {len(recent_only)} msgs "
            f"({actual_ratio:.1%} ratio, {chars_saved} chars saved)"
        )

        return CompressedContext(
            original_messages=messages,
            compressed_text=full_compressed,
            key_points=key_points,
            compression_ratio=actual_ratio,
            metadata=(original_length, compressed_length),
            original_length=original_length,
            compressed_length=compressed_length,
            timestamp=start_time
        )

    async def _llm_compress(
        self,
        messages: List[Tuple[str, str]],
        key_points: List[str]
    ) -> str:
        """
        Use 8B lightweight LLM to create a high-quality semantic summary.

        The summary produced here is the ONLY record of the compressed context.
        Everything before the compression point is discarded.  The prompt must
        instruct the model to preserve all task-critical information so the
        VLM can continue reasoning without loss.
        """
        # Format messages for summarization
        formatted = "\n".join(
            f"[{role.upper()}] {content.strip()}"
            for role, content in messages
        )

        # Task-aware compression prompt — tells the 8B model exactly what
        # the VLM needs to continue working after compression.
        prompt = f"""You are a context compression agent for an autonomous AI system.
The AI is in the middle of executing a task.  Everything before this summary
will be DISCARDED, so this summary is the ONLY record of what happened.

CONVERSATION TO COMPRESS:
{formatted}

KEY POINTS TO PRESERVE:
{chr(10).join(f'- {point}' for point in key_points)}

You MUST preserve ALL of the following in your summary:
1. TOOL RESULTS: Every tool call and its output (success or failure)
2. DECISIONS: Any decisions made and their reasoning
3. ERRORS & FAILURES: What failed and why (critical for avoiding retries)
4. DISCOVERIES: Facts, data, or insights found during execution
5. CURRENT STATE: Where the task is right now and what remains to be done
6. ENVIRONMENT CONTEXT: File paths, URLs, config values, IDs, or names mentioned

Do NOT:
- Omit tool outputs or error messages
- Add opinions or analysis not present in the original
- Use vague language like "various tools were used"

Write a dense, factual summary. Preserve exact values, paths, and identifiers.

SUMMARY:"""

        try:
            # Use 8B lightweight LLM for summarization
            summary = await self._call_llm(
                prompt,
                max_tokens=800,       # Allow richer summaries (was 500)
                temperature=0.2,      # Low temperature for factual accuracy
            )

            # Clean up response
            if summary.startswith('"') and summary.endswith('"'):
                summary = summary[1:-1]

            if "SUMMARY:" in summary:
                summary_start = summary.index("SUMMARY:")
                summary = summary[summary_start + len("SUMMARY:"):].strip()

            return summary

        except Exception as e:
            logger.error(f"LLM compression failed: {e}")
            return f"[Conversation summary unavailable: {str(e)}]"

    async def _call_llm(self, prompt: str, **kwargs) -> str:
        """Call LLM for summarization"""
        try:
            from core.services.lightweight_llm import get_lightweight_llm_service

            llm = get_lightweight_llm_service()

            response = await llm.generate(
                prompt=prompt,
                agent_type="context_compressor",
                **kwargs
            )

            # Extract text from response dict
            if isinstance(response, dict):
                return response.get('content', '')
            else:
                return str(response)

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""

    async def _rule_based_compress(
        self,
        messages: List[Tuple[str, str]]
    ) -> str:
        """
        Rule-based compression (no LLM needed)
        Uses heuristics to compress messages
        """
        compressed_parts = []

        for role, content in messages:
            content_stripped = content.strip()

            # Skip very short messages
            if len(content_stripped) < 50:
                compressed_parts.append(f"{role}: {content_stripped}")
                continue

            # Extract sentences
            sentences = self._split_sentences(content)

            # Keep first and last sentences (often most important)
            if len(sentences) >= 3:
                kept = [sentences[0]] + [sentences[-1]]
            else:
                kept = sentences

            # Remove redundant content
            kept_unique = []
            for sent in kept:
                if not any(self._is_similar(sent, existing) for existing in kept_unique):
                    kept_unique.append(sent)

            compressed = '. '.join(kept_unique)
            compressed_parts.append(f"{role}: {compressed}")

        # Join with separators
        result = '\n---\n'.join(compressed_parts)

        return result

    async def _extract_key_points(
        self,
        messages: List[Tuple[str, str]],
        target_ratio: float
    ) -> List[str]:
        """
        Extract key points from messages

        Args:
            messages: Messages to extract from
            target_ratio: Target compression ratio

        Returns:
            List of key points
        """
        # Calculate how many points to extract
        num_points = max(3, int(len(messages) * (1 - target_ratio)))

        key_points = []

        logger.info(f"Extracting {num_points} key points")
        logger.info(f"  from {len(messages)} messages")

        # Score each message by importance
        scored = []
        for role, content in messages:
            score = self._importance_score(content)

            if score > 0:
                # Extract the most important sentence
                sentences = self._split_sentences(content)
                if sentences:
                    best_sentence = max(sentences, key=self._importance_score)
                    scored.append((score, best_sentence))

        # Sort by score and take top N
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, point in scored[:num_points]:
            # Truncate long points
            if len(point) > 200:
                point = point[:197] + "..."
            key_points.append(point)

        return key_points

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences"""
        # Simple sentence splitting
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    def _importance_score(self, text: str) -> float:
        """Calculate importance score for text"""
        score = len(text)

        # Boost for important keywords
        important_words = [
            # Action words
            "decide", "need", "must", "should", "will",
            "create", "build", "implement",

            # Factual words
            "fact", "data", "result", "found", "discovered",
            "error", "issue",

            # Decision words
            "because", "therefore", "since", "thus",
            "however", "although",

            # Quantitative
            "number", "count", "total", "percent",

            # Critical
            "critical", "important", "key", "essential",
            "required", "necessary"
        ]

        for word in important_words:
            if word.lower() in text.lower():
                score += 50

        return score

    def _is_similar(
        self,
        text1: str,
        text2: str
    ) -> bool:
        """
        Check if two texts are similar (for deduplication)
        Simple word overlap check
        """
        # Normalize and tokenize
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return False  # Can't compare empty

        # Calculate overlap
        overlap = len(words1 & words2) / min(len(words1), len(words2))

        return overlap > 0.7

    async def _remove_redundancy(
        self,
        messages: List[Tuple[str, str]],
        key_points: List[str]
    ) -> List[Tuple[str, str]]:
        """
        Remove redundant information from messages based on key points
        """
        # Track what's already captured in key points
        captured = set()
        for point in key_points:
            captured.update(point.lower().split())

        # Filter messages to remove redundant content
        filtered = []
        for role, content in messages:
            words = set(content.lower().split())
            new_info = words - captured

            # Keep if it has substantial new information
            if len(new_info) / len(words) > 0.3:
                filtered.append((role, content))
                captured.update(words)

        return filtered

    def _format_messages(
        self,
        messages: List[Tuple[str, str]]
    ) -> str:
        """
        Format messages into readable text

        Args:
            messages: List of (role, content) tuples

        Returns:
            Formatted string
        """
        return '\n\n'.join(
            f"{role.upper()}: {content.strip()}"
            for role, content in messages
        )

    async def compress_with_strategy(
        self,
        messages: List[Tuple[str, str]],
        strategy: str = "balanced"
    ) -> CompressedContext:
        """
        Compress using a named strategy

        Strategies:
        - aggressive: High compression (0.3 ratio), minimal context preserved
        - balanced: Medium compression (0.5 ratio), good balance
        - conservative: Light compression (0.7 ratio), most context preserved
        """
        logger.info(
            f"Compressing {len(messages)} messages with '{strategy}' strategy"
        )

    async def get_statistics(self) -> Dict[str, Any]:
        """Get compression statistics"""
        return self.stats.copy()


# Singleton instance
_context_compression: Optional[ContextCompression] = None


def get_context_compression() -> ContextCompression:
    """Get global context compression instance"""
    global _context_compression
    if _context_compression is None:
        _context_compression = ContextCompression()
    return _context_compression


# CLI test
async def main():
    """Test context compression"""
    logging.basicConfig(level=logging.INFO)

    compressor = get_context_compression()

    print("\n=== Context Compression Test ===")

    # Test messages
    messages = [
        ("user", "I need help building a recommendation system for my e-commerce site."),
        ("assistant", "I can help you build a recommendation system. There are several approaches we can take: collaborative filtering, content-based filtering, or hybrid methods. What kind of products does your site sell?"),
        ("user", "We sell books and electronics. We have about 10,000 products and 50,000 users."),
        ("assistant", "Great! For a catalog of that size, I'd recommend starting with a hybrid approach that combines collaborative filtering (based on user behavior) with content-based filtering (based on product attributes). Let me walk you through the implementation steps..."),
        ("user", "Sounds good. How do we handle cold start problems?"),
        ("assistant", "Cold start is indeed a challenge. For new users with no history, we can use: 1) Popular items as defaults, 2) Ask for initial preferences, 3) Use demographic information if available. For new products, we can rely on content-based features until we gather user interactions.")
    ]

    # Compress
    result = await compressor.compress_context(
        messages=messages,
        target_ratio=0.5,
        preserve_recent=2,
        use_llm=False
    )

    print(f"\nOriginal: {len(messages)} messages")
    print(f"Compressed ratio: {result.compression_ratio:.1%}")
    print(f"Key points extracted: {len(result.key_points)}")

    print("\nKey Points:")
    for i, point in enumerate(result.key_points, 1):
        print(f"  {i}. {point}")

    # Get statistics
    stats = await compressor.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
