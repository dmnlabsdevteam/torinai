#!/usr/bin/env python3
"""
Seed Intrinsic Motivation System with Realistic Historical Data

This populates the in-memory state of the intrinsic motivation system
with fake but realistic data based on observed system behavior.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
from core.agents.autonomous.intrinsic_motivation import GoalEmbedding


async def seed_realistic_history(motivation_system):
    """
    Seed intrinsic motivation system with realistic historical patterns
    based on actual observed behavior during development.
    """

    print("=" * 80)
    print("SEEDING REALISTIC HISTORICAL DATA")
    print("=" * 80)
    print()

    # ========================================================================
    # 1. GOAL HISTORY: Past goals attempted (for novelty calculation)
    # ========================================================================
    print("📊 Seeding goal history...")

    # Simulate past goals that were attempted
    past_goals = [
        "Monitor system health and resource usage",
        "Identify performance bottlenecks in task execution",
        "Analyze slack notification timeout patterns",
        "Explore database query optimization opportunities",
        "Investigate memory agent connection stability",
        "Research frontier models for capability expansion",
        "Evaluate neural bridge reasoning quality",
        "Assess tool selection accuracy patterns",
    ]

    # Create embeddings for past goals (simulated)
    if motivation_system._embedding_service:
        for i, goal_desc in enumerate(past_goals):
            # Create fake embedding (normally would be actual semantic embedding)
            fake_embedding = [0.1 * j + 0.01 * i for j in range(384)]  # 384-dim vector

            goal_emb = GoalEmbedding(
                goal_id=f"historical_goal_{i:03d}",
                goal_description=goal_desc,
                theme=_extract_theme(goal_desc),
                embedding=fake_embedding,
                timestamp=datetime.now() - timedelta(days=30-i)
            )
            motivation_system._goal_embeddings.append(goal_emb)

        print(f"  ✓ Seeded {len(motivation_system._goal_embeddings)} past goal embeddings")
    else:
        print(f"  ⚠ Embedding service not available, skipping goal embeddings")

    # ========================================================================
    # 2. THEME REPETITION: Track how often each theme has been explored
    # ========================================================================
    print("📊 Seeding theme repetition counts...")

    theme_counts = {
        'monitoring': 8,           # Heavily explored
        'performance': 5,          # Moderately explored
        'debugging': 4,            # Some exploration
        'research': 2,             # Lightly explored
        'optimization': 3,         # Lightly explored
        'analysis': 6,             # Moderately explored
    }

    motivation_system._theme_counts = theme_counts
    print(f"  ✓ Seeded {len(theme_counts)} theme repetition counts")
    for theme, count in theme_counts.items():
        print(f"    - {theme}: {count} times")

    # ========================================================================
    # 3. COMPONENT BASELINES: Performance baselines for each component
    # ========================================================================
    print("📊 Seeding component performance baselines...")

    # Based on observed failures: general_purpose_executor and slack_notifier are problematic
    component_baselines = {
        'general_purpose_executor': {
            'epistemic_uncertainty': 0.72,  # High uncertainty - tool selection issues
            'impact_radius': 0.85,          # High impact - core execution
            'performance_degradation': 0.60, # Moderate degradation
            'novelty_potential': 0.55       # Some novelty potential
        },
        'slack_notifier': {
            'epistemic_uncertainty': 0.68,  # High uncertainty - timeout issues
            'impact_radius': 0.40,          # Medium impact - communication layer
            'performance_degradation': 0.75, # High degradation - frequent timeouts
            'novelty_potential': 0.30       # Low novelty - well understood
        },
        'memory_agent': {
            'epistemic_uncertainty': 0.35,  # Low uncertainty - stable
            'impact_radius': 0.70,          # High impact - memory is critical
            'performance_degradation': 0.20, # Low degradation - working well
            'novelty_potential': 0.45       # Moderate novelty
        },
        'neural_bridge': {
            'epistemic_uncertainty': 0.45,  # Moderate uncertainty
            'impact_radius': 0.80,          # Very high impact - reasoning core
            'performance_degradation': 0.30, # Low-moderate degradation
            'novelty_potential': 0.65       # High novelty potential
        },
        'unified_llm': {
            'epistemic_uncertainty': 0.50,  # Moderate uncertainty
            'impact_radius': 0.95,          # Critical impact - the brain
            'performance_degradation': 0.25, # Low degradation
            'novelty_potential': 0.40       # Moderate novelty
        }
    }

    motivation_system._component_baselines = component_baselines
    print(f"  ✓ Seeded {len(component_baselines)} component baselines")
    for comp, metrics in component_baselines.items():
        print(f"    - {comp}: uncertainty={metrics['epistemic_uncertainty']:.2f}, impact={metrics['impact_radius']:.2f}")

    # ========================================================================
    # 4. METRIC HISTORY: Historical metrics showing trends
    # ========================================================================
    print("📊 Seeding metric history (showing trends)...")

    # Simulate degrading performance for problematic components
    metric_history = {
        'general_purpose_executor': [
            {'epistemic_uncertainty': 0.45, 'performance_degradation': 0.30},  # 5 iterations ago
            {'epistemic_uncertainty': 0.55, 'performance_degradation': 0.40},  # 4 iterations ago
            {'epistemic_uncertainty': 0.62, 'performance_degradation': 0.50},  # 3 iterations ago
            {'epistemic_uncertainty': 0.68, 'performance_degradation': 0.55},  # 2 iterations ago
            {'epistemic_uncertainty': 0.72, 'performance_degradation': 0.60},  # 1 iteration ago (current)
        ],
        'slack_notifier': [
            {'epistemic_uncertainty': 0.50, 'performance_degradation': 0.60},
            {'epistemic_uncertainty': 0.58, 'performance_degradation': 0.65},
            {'epistemic_uncertainty': 0.63, 'performance_degradation': 0.70},
            {'epistemic_uncertainty': 0.66, 'performance_degradation': 0.73},
            {'epistemic_uncertainty': 0.68, 'performance_degradation': 0.75},
        ],
        'memory_agent': [
            {'epistemic_uncertainty': 0.35, 'performance_degradation': 0.20},
            {'epistemic_uncertainty': 0.34, 'performance_degradation': 0.19},
            {'epistemic_uncertainty': 0.35, 'performance_degradation': 0.21},
            {'epistemic_uncertainty': 0.36, 'performance_degradation': 0.20},
            {'epistemic_uncertainty': 0.35, 'performance_degradation': 0.20},
        ],
    }

    motivation_system._metric_history = metric_history
    print(f"  ✓ Seeded metric history for {len(metric_history)} components")
    print(f"    - Showing performance trends (degrading for problematic components)")

    # ========================================================================
    # 5. TOOL USAGE PATTERNS: Recent tool sequences
    # ========================================================================
    print("📊 Seeding tool usage patterns...")

    # Simulate repetitive tool usage (looping behavior)
    tool_sequences = [
        ['web_search', 'read_file', 'slack_notify'],
        ['web_search', 'read_file', 'slack_notify'],  # Repeated sequence
        ['database_query', 'analyze_data'],
        ['web_search', 'read_file', 'slack_notify'],  # Repeated again (problematic!)
        ['system_monitor', 'log_analysis'],
    ]

    motivation_system._tool_sequence_history = tool_sequences
    print(f"  ✓ Seeded {len(tool_sequences)} tool sequences")
    print(f"    - Pattern shows repetition (indicates possible loop behavior)")

    # ========================================================================
    # 6. TOOL FAILURE COUNTS: Tools that have been failing
    # ========================================================================
    print("📊 Seeding tool failure counts...")

    tool_failures = {
        'slack_notify': 1,          # Close to cooldown threshold (2 failures)
        'web_search': 0,            # Working fine
        'database_query': 1,        # Some failures
    }

    motivation_system._tool_failure_counts = tool_failures
    print(f"  ✓ Seeded {len(tool_failures)} tool failure counts")
    for tool, count in tool_failures.items():
        print(f"    - {tool}: {count} failures")

    # ========================================================================
    # 7. RECENT GOAL DESCRIPTIONS: To avoid immediate repetition
    # ========================================================================
    print("📊 Seeding recent goal descriptions...")

    recent_goals = [
        "Monitor system health",
        "Analyze slack timeout patterns",
        "Investigate tool selection mismatches"
    ]

    motivation_system._recent_goal_descriptions = recent_goals
    print(f"  ✓ Seeded {len(recent_goals)} recent goal descriptions")

    print()
    print("=" * 80)
    print("HISTORICAL DATA SEEDING COMPLETE")
    print("=" * 80)
    print()
    print("Key patterns seeded:")
    print("  - general_purpose_executor: Rising uncertainty (0.45 → 0.72)")
    print("  - slack_notifier: Degrading performance (0.60 → 0.75)")
    print("  - Tool sequence repetition detected (potential loop)")
    print("  - Monitoring theme heavily explored (8x)")
    print("  - Research theme lightly explored (2x)")
    print()


def _extract_theme(goal_description: str) -> str:
    """Extract theme from goal description for categorization"""
    goal_lower = goal_description.lower()

    if 'monitor' in goal_lower or 'health' in goal_lower:
        return 'monitoring'
    elif 'performance' in goal_lower or 'bottleneck' in goal_lower:
        return 'performance'
    elif 'debug' in goal_lower or 'investigate' in goal_lower or 'analyze' in goal_lower:
        return 'debugging'
    elif 'research' in goal_lower or 'explore' in goal_lower or 'frontier' in goal_lower:
        return 'research'
    elif 'optimize' in goal_lower or 'improve' in goal_lower:
        return 'optimization'
    else:
        return 'analysis'


if __name__ == "__main__":
    print("This module is meant to be imported and used by test_intrinsic_motivation.py")
    print("Run: python test_intrinsic_motivation.py")
