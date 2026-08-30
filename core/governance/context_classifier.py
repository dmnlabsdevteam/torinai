"""
Context Classifier for Governance Quality

Non-destructive labeling system that classifies context items before governance triggering.
Improves governance context quality, human review clarity, and audit defensibility.

CRITICAL PRINCIPLE: NO DELETION
This system ONLY labels/classifies information. It NEVER deletes, scrubs, or removes any data.
All original data is preserved and available.

Labels:
- TRANSIENT: Temporary tool outputs, scratch analysis
- REFERENTIAL: External documentation, API responses, reference materials
- DECISIONAL: Information used in making the governance decision
- AUDIT_RELEVANT: Must be preserved for audit trail (compliance, legal, safety)
- MEMORY_CANDIDATE: Candidate for promotion to permanent memory
"""

import logging
from enum import Enum
from typing import List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextLabel(Enum):
    """
    Non-destructive labels for context classification.

    These labels help organize information for governance review,
    but DO NOT result in deletion or filtering.
    """

    # Temporary analysis, tool outputs, scratch work
    TRANSIENT = "transient"

    # External documentation, API responses, reference materials
    REFERENTIAL = "referential"

    # Information used in making the governance decision
    DECISIONAL = "decisional"

    # Must be preserved for audit trail (compliance, legal, safety)
    AUDIT_RELEVANT = "audit_relevant"

    # Candidate for promotion to permanent memory
    MEMORY_CANDIDATE = "memory_candidate"


@dataclass
class ClassifiedContext:
    """
    Context item with non-destructive classification label.

    Original data is NEVER modified or deleted.
    """
    content: Any
    label: ContextLabel
    confidence: float  # 0.0 to 1.0
    classification_reason: str
    classified_at: datetime
    metadata: Dict[str, Any]


class ContextClassifier:
    """
    Classifies context before governance triggering.

    CRITICAL: This is LABELING ONLY - no deletion, no filtering, no scrubbing.
    All original data is preserved and available.
    """

    async def classify_context(
        self,
        context_items: List[Dict[str, Any]]
    ) -> List[ClassifiedContext]:
        """
        Label each context item with appropriate classification.

        Args:
            context_items: Raw context data from action preparation

        Returns:
            Same items with classification labels added (no deletion)
        """
        classified = []

        for item in context_items:
            label, confidence, reason = await self._determine_label(item)

            classified.append(ClassifiedContext(
                content=item,  # Original content preserved
                label=label,
                confidence=confidence,
                classification_reason=reason,
                classified_at=datetime.now(),
                metadata=self._extract_metadata(item)
            ))

        # Verify no data loss
        assert len(classified) == len(context_items), \
            "Context classifier must preserve all items (no deletion)"

        logger.info(f"Classified {len(classified)} context items")
        return classified

    async def _determine_label(
        self,
        item: Dict[str, Any]
    ) -> tuple[ContextLabel, float, str]:
        """
        Determine appropriate label for context item.

        Returns:
            (label, confidence, reasoning)
        """
        # Check for audit-relevant markers (highest priority)
        if self._is_audit_relevant(item):
            return (
                ContextLabel.AUDIT_RELEVANT,
                0.95,
                "Contains governance decision, safety constraint, or compliance data"
            )

        # Check for decisional information
        if self._is_decisional(item):
            return (
                ContextLabel.DECISIONAL,
                0.90,
                "Contains reasoning, action parameters, or decision factors"
            )

        # Check for memory candidates
        if self._is_memory_candidate(item):
            return (
                ContextLabel.MEMORY_CANDIDATE,
                0.85,
                "Contains insight, pattern, or learning that should be preserved"
            )

        # Check for external references
        if self._is_referential(item):
            return (
                ContextLabel.REFERENTIAL,
                0.80,
                "External documentation, API response, or reference material"
            )

        # Default to transient
        return (
            ContextLabel.TRANSIENT,
            0.70,
            "Temporary tool output or scratch analysis"
        )

    def _is_audit_relevant(self, item: Dict[str, Any]) -> bool:
        """Check if item is audit-critical"""
        audit_markers = [
            "governance_decision",
            "safety_constraint",
            "compliance_requirement",
            "human_approval",
            "commitment_contract",
            "policy_violation",
            "execution_mode"
        ]

        item_type = item.get("type", "")
        content = str(item.get("content", "")).lower()

        return (
            item_type in audit_markers or
            any(marker in content for marker in audit_markers)
        )

    def _is_decisional(self, item: Dict[str, Any]) -> bool:
        """Check if item contains decision-relevant information"""
        decisional_markers = [
            "action_parameters",
            "reasoning",
            "risk_assessment",
            "impact_analysis",
            "alternative_considered",
            "constraint_check"
        ]

        item_type = item.get("type", "")
        return item_type in decisional_markers

    def _is_memory_candidate(self, item: Dict[str, Any]) -> bool:
        """Check if item should be considered for memory storage"""
        memory_markers = [
            "pattern_recognition",
            "insight",
            "lesson_learned",
            "strategy_formation",
            "behavior_adjustment"
        ]

        item_type = item.get("type", "")
        return item_type in memory_markers

    def _is_referential(self, item: Dict[str, Any]) -> bool:
        """Check if item is external reference material"""
        referential_markers = [
            "external_documentation",
            "api_response",
            "library_reference",
            "external_data"
        ]

        item_type = item.get("type", "")
        source = item.get("source", "")
        content_str = str(item.get("content", ""))

        return (
            item_type in referential_markers or
            source.startswith("external_") or
            "http://" in content_str or
            "https://" in content_str
        )

    def _extract_metadata(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Extract useful metadata for governance display"""
        return {
            "item_type": item.get("type", "unknown"),
            "source": item.get("source", "unknown"),
            "timestamp": item.get("timestamp", datetime.now().isoformat()),
            "size_bytes": len(str(item.get("content", ""))),
            "has_action_reference": "action_id" in item
        }

    def format_context_for_judges(
        self,
        classified_context: List[ClassifiedContext]
    ) -> str:
        """
        Format classified context for human/AI judge review.

        Groups by label to improve readability, but includes ALL content.
        """
        formatted = "# Governance Context (Classified)\n\n"

        # Group by label for easier review
        by_label = {}
        for item in classified_context:
            label = item.label.value
            if label not in by_label:
                by_label[label] = []
            by_label[label].append(item)

        # Present in priority order
        priority_order = [
            ContextLabel.AUDIT_RELEVANT,
            ContextLabel.DECISIONAL,
            ContextLabel.MEMORY_CANDIDATE,
            ContextLabel.REFERENTIAL,
            ContextLabel.TRANSIENT
        ]

        for label in priority_order:
            if label.value in by_label:
                items = by_label[label.value]
                formatted += f"## {label.value.upper()} ({len(items)} items)\n\n"

                for item in items:
                    formatted += f"**Classification Reason**: {item.classification_reason}\n"
                    formatted += f"**Confidence**: {item.confidence:.2f}\n"
                    formatted += f"**Metadata**: {item.metadata}\n"
                    formatted += f"**Content**:\n```\n{item.content}\n```\n\n"

        formatted += "\n---\n"
        formatted += "**Note**: All context is preserved and available. "
        formatted += "Labels are for organizational purposes only.\n"

        return formatted


# Verification function
def verify_no_data_loss(
    original_items: List[Dict[str, Any]],
    classified_items: List[ClassifiedContext]
) -> bool:
    """
    Verify that context classifier preserved all data.

    This function ensures the critical "NO DELETION" principle.
    """
    # Check count
    if len(original_items) != len(classified_items):
        logger.error(
            f"Data loss detected: {len(original_items)} original items, "
            f"{len(classified_items)} classified items"
        )
        return False

    # Check content integrity
    for original, classified in zip(original_items, classified_items):
        if original != classified.content:
            logger.error("Content modification detected")
            return False

    logger.info("✓ Verification passed: No data loss, no content modification")
    return True
