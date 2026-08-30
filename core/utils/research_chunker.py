#!/usr/bin/env python3
"""
Research Data Chunker
=====================
Splits large research datasets into logical chunks for document generation

Purpose:
- Prevent token overflow when generating documents
- Group research findings by topic
- Maintain logical boundaries
- Enable multi-pass document generation

Author: Dominion Labs
Version: 1.0
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResearchChunk:
    """Single chunk of research data"""
    chunk_id: str
    findings: List[Dict[str, Any]]
    topic_summary: str
    total_tokens: int
    chunk_index: int
    total_chunks: int


class ResearchChunker:
    """
    Chunk large research datasets for multi-pass document generation

    Strategy:
    - Group findings by topic/category
    - Limit chunk size to token budget
    - Preserve logical boundaries
    - Maintain context across chunks

    Usage:
        chunker = ResearchChunker(max_tokens_per_chunk=1000)
        chunks = chunker.chunk_research_findings(findings)

        for chunk in chunks:
            partial_doc = await generate_section(chunk.findings, chunk.topic_summary)
            partials.append(partial_doc)

        final_doc = combine_partials(partials)
    """

    def __init__(self, max_tokens_per_chunk: int = 1000):
        """
        Initialize Research Chunker

        Args:
            max_tokens_per_chunk: Maximum tokens per chunk (default 1000)
        """
        self.max_tokens_per_chunk = max_tokens_per_chunk
        logger.info(f"ResearchChunker initialized: max_tokens={max_tokens_per_chunk}")

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Simple estimation: word count * 1.3
        return int(len(str(text).split()) * 1.3)

    def chunk_research_findings(
        self,
        findings: List[Dict[str, Any]],
        group_by_key: str = 'topic'
    ) -> List[ResearchChunk]:
        """
        Split research findings into chunks

        Args:
            findings: List of research finding dicts
            group_by_key: Key to group findings by (default 'topic')

        Returns:
            List of ResearchChunk objects
        """
        if not findings:
            logger.warning("No findings to chunk")
            return []

        # Group by topic/category
        topic_groups = self._group_findings(findings, group_by_key)

        # Create chunks respecting token limits
        chunks = self._create_chunks(topic_groups)

        logger.info(
            f"Chunked {len(findings)} findings into {len(chunks)} chunks "
            f"(avg {len(findings) // max(len(chunks), 1)} findings per chunk)"
        )

        return chunks

    def _group_findings(
        self,
        findings: List[Dict[str, Any]],
        group_by_key: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group findings by specified key

        Args:
            findings: List of research findings
            group_by_key: Key to group by

        Returns:
            Dict mapping topic -> list of findings
        """
        topic_groups = {}

        for finding in findings:
            # Get topic (default to 'general' if not present)
            topic = finding.get(group_by_key, 'general')

            if isinstance(topic, list):
                # Handle case where topic is a list
                topic = topic[0] if topic else 'general'

            topic = str(topic)

            if topic not in topic_groups:
                topic_groups[topic] = []

            topic_groups[topic].append(finding)

        logger.debug(f"Grouped into {len(topic_groups)} topics: {list(topic_groups.keys())}")
        return topic_groups

    def _create_chunks(
        self,
        topic_groups: Dict[str, List[Dict[str, Any]]]
    ) -> List[ResearchChunk]:
        """
        Create chunks from topic groups

        Args:
            topic_groups: Dict mapping topic -> findings

        Returns:
            List of ResearchChunk objects
        """
        chunks = []
        chunk_id = 0

        for topic, group_findings in topic_groups.items():
            # Split large topic groups into multiple chunks
            current_chunk_findings = []
            current_tokens = 0

            for finding in group_findings:
                # Estimate finding size
                finding_text = str(finding)
                finding_tokens = self.estimate_tokens(finding_text)

                # Check if adding this finding would exceed limit
                if current_tokens + finding_tokens > self.max_tokens_per_chunk and current_chunk_findings:
                    # Create chunk from accumulated findings
                    chunks.append(self._make_chunk(
                        chunk_id=f"chunk_{chunk_id}",
                        findings=current_chunk_findings,
                        topic=topic,
                        total_tokens=current_tokens,
                        chunk_index=chunk_id
                    ))
                    chunk_id += 1

                    # Start new chunk
                    current_chunk_findings = []
                    current_tokens = 0

                # Add finding to current chunk
                current_chunk_findings.append(finding)
                current_tokens += finding_tokens

            # Add remaining findings as final chunk for this topic
            if current_chunk_findings:
                chunks.append(self._make_chunk(
                    chunk_id=f"chunk_{chunk_id}",
                    findings=current_chunk_findings,
                    topic=topic,
                    total_tokens=current_tokens,
                    chunk_index=chunk_id
                ))
                chunk_id += 1

        # Set total_chunks for all chunks
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk.total_chunks = total_chunks

        return chunks

    def _make_chunk(
        self,
        chunk_id: str,
        findings: List[Dict[str, Any]],
        topic: str,
        total_tokens: int,
        chunk_index: int
    ) -> ResearchChunk:
        """
        Create a ResearchChunk object

        Args:
            chunk_id: Unique chunk identifier
            findings: List of findings in this chunk
            topic: Topic name
            total_tokens: Estimated token count
            chunk_index: Index of this chunk

        Returns:
            ResearchChunk instance
        """
        return ResearchChunk(
            chunk_id=chunk_id,
            findings=findings,
            topic_summary=f"Research on {topic} (part {chunk_index + 1})",
            total_tokens=total_tokens,
            chunk_index=chunk_index,
            total_chunks=0  # Will be set later
        )

    def chunk_text(
        self,
        text: str,
        overlap_tokens: int = 100
    ) -> List[str]:
        """
        Chunk large text into overlapping sections

        Useful for splitting single large documents that exceed token limits

        Args:
            text: Text to chunk
            overlap_tokens: Number of tokens to overlap between chunks

        Returns:
            List of text chunks
        """
        if not text:
            return []

        total_tokens = self.estimate_tokens(text)

        if total_tokens <= self.max_tokens_per_chunk:
            # Text fits in single chunk
            return [text]

        # Split into sentences for clean boundaries
        sentences = text.split('. ')

        chunks = []
        current_chunk = []
        current_tokens = 0
        overlap_sentences = []

        for sentence in sentences:
            sentence_tokens = self.estimate_tokens(sentence)

            if current_tokens + sentence_tokens > self.max_tokens_per_chunk and current_chunk:
                # Create chunk
                chunk_text = '. '.join(current_chunk) + '.'
                chunks.append(chunk_text)

                # Keep last few sentences for overlap
                overlap_size = 0
                overlap_sentences = []
                for s in reversed(current_chunk):
                    s_tokens = self.estimate_tokens(s)
                    if overlap_size + s_tokens <= overlap_tokens:
                        overlap_sentences.insert(0, s)
                        overlap_size += s_tokens
                    else:
                        break

                # Start new chunk with overlap
                current_chunk = overlap_sentences.copy()
                current_tokens = overlap_size

            current_chunk.append(sentence)
            current_tokens += sentence_tokens

        # Add final chunk
        if current_chunk:
            chunk_text = '. '.join(current_chunk) + '.'
            chunks.append(chunk_text)

        logger.info(f"Chunked text into {len(chunks)} overlapping chunks")
        return chunks


# Singleton instance
_research_chunker = None


def get_research_chunker(max_tokens_per_chunk: int = 1000) -> ResearchChunker:
    """
    Get or create global research chunker instance

    Args:
        max_tokens_per_chunk: Maximum tokens per chunk

    Returns:
        ResearchChunker instance
    """
    global _research_chunker

    if _research_chunker is None:
        _research_chunker = ResearchChunker(max_tokens_per_chunk)

    return _research_chunker
