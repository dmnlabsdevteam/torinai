#!/usr/bin/env python3
"""
Query Analysis System Test
===========================
Tests the intelligent query analysis that determines when to search memories.

Validates:
1. Hard reject patterns (never search)
2. Hard accept patterns (always search)
3. Soft threshold patterns (heuristic-based)
4. Performance impact of selective searching
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Relevance has ONE authority: MemoryInjectionPolicy.decide(). These tests
# previously called MemoryInjector._should_search_memories(), a second gate
# that was removed when the three competing answers were consolidated (see
# tests/test_memory_injection_authority.py). They assert the same behaviour
# against the surviving authority rather than resurrecting the duplicate.
from core.memory.utils.memory_injection_policy import get_memory_injection_policy


def test_hard_reject_queries():
    """Test queries that should NEVER trigger memory search"""
    injector = get_memory_injection_policy()

    test_cases = [
        # Very short queries
        ("hello", False, "greeting"),
        ("thanks", False, "acknowledgment"),
        ("ok", False, "confirmation"),

        # Simple arithmetic
        ("what is 2+2", False, "simple math"),
        ("calculate 5*3", False, "basic calculation"),

        # Simple factual lookups
        ("define Python", False, "single-word definition"),
        ("who is Einstein", False, "simple who-is"),
        ("where is Paris", False, "simple where-is"),

        # Isolated task commands
        ("list files", False, "isolated list command"),
        ("show status", False, "isolated show command"),
        ("run tests", False, "isolated run command"),
    ]

    print("\n" + "="*80)
    print("HARD REJECT QUERIES (Should NOT search)")
    print("="*80)

    passed = 0
    failed = 0

    for query, expected, description in test_cases:
        result = injector.decide(query).enabled
        status = "✓" if result == expected else "✗"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} {description:30} | Query: '{query:30}' | Expected: {expected:5} | Got: {result:5}")

    print(f"\nPassed: {passed}/{len(test_cases)}")
    return failed == 0


def test_hard_accept_queries():
    """Test queries that should ALWAYS trigger memory search"""
    injector = get_memory_injection_policy()

    test_cases = [
        # Past references
        ("what did we discuss about the memory system?", True, "past discussion reference"),
        ("remember when we implemented the filter?", True, "remember keyword"),
        ("you mentioned something about swarm search earlier", True, "you mentioned"),

        # Context-dependent
        ("why did you choose that approach?", True, "why did"),
        ("explain why the system works this way", True, "explain why"),
        ("tell me about the neural bridge architecture", True, "tell me about"),

        # Multi-step reasoning
        ("analyze the performance impact of memory injection on query latency", True, "analyze complex"),
        ("compare the memory filter and query analysis approaches", True, "compare"),

        # Synthesis
        ("what is the relationship between memory filtering and query analysis?", True, "relationship"),
        ("how do the memory and reasoning systems integrate?", True, "integration"),

        # Strategic
        ("what's the best way to optimize memory search performance?", True, "best way"),
        ("should we implement caching for frequently accessed memories?", True, "should we"),
    ]

    print("\n" + "="*80)
    print("HARD ACCEPT QUERIES (Should ALWAYS search)")
    print("="*80)

    passed = 0
    failed = 0

    for query, expected, description in test_cases:
        result = injector.decide(query).enabled
        status = "✓" if result == expected else "✗"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} {description:30} | Expected: {expected:5} | Got: {result:5}")

    print(f"\nPassed: {passed}/{len(test_cases)}")
    return failed == 0


def test_soft_threshold_queries():
    """Test queries evaluated by heuristic thresholds"""
    injector = get_memory_injection_policy()

    test_cases = [
        # Long queries (> 60 chars)
        ("This is a somewhat complex query that has many words and exceeds the character threshold", True, "long query"),

        # Multiple questions
        ("What is the memory filter? How does it work? Why was it designed this way?", True, "multiple questions"),

        # Word count threshold (>= 10 words)
        ("I need to understand how the memory system determines what to store and retrieve", True, "10+ words"),

        # Technical terminology with context
        ("how does the neural bridge agent interact with the memory query system", True, "technical terms"),

        # Medium queries without markers (should reject)
        ("simple request without complexity", False, "medium simple query"),
        ("just a basic query here", False, "basic query"),
    ]

    print("\n" + "="*80)
    print("SOFT THRESHOLD QUERIES (Heuristic-based)")
    print("="*80)

    passed = 0
    failed = 0

    for query, expected, description in test_cases:
        result = injector.decide(query).enabled
        status = "✓" if result == expected else "✗"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} {description:30} | Expected: {expected:5} | Got: {result:5}")

    print(f"\nPassed: {passed}/{len(test_cases)}")
    return failed == 0


def test_edge_cases():
    """Test edge cases and boundary conditions"""
    injector = get_memory_injection_policy()

    test_cases = [
        # Empty/None queries
        ("", False, "empty string"),
        ("   ", False, "whitespace only"),

        # Exactly at thresholds
        ("exactly10", False, "exactly 10 chars (at threshold)"),
        ("this query has exactly ten words in it right here now", True, "exactly 10 words"),

        # Mixed patterns
        ("what is the strategic approach we should take for memory optimization?", True, "simple start + strategic"),
        ("define the architecture we discussed last time", True, "simple start + past reference"),
    ]

    print("\n" + "="*80)
    print("EDGE CASES")
    print("="*80)

    passed = 0
    failed = 0

    for query, expected, description in test_cases:
        result = injector.decide(query).enabled
        status = "✓" if result == expected else "✗"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} {description:30} | Expected: {expected:5} | Got: {result:5}")

    print(f"\nPassed: {passed}/{len(test_cases)}")
    return failed == 0


def main():
    """Run all query analysis tests"""
    print("\n" + "="*80)
    print("QUERY ANALYSIS SYSTEM TEST")
    print("Testing intelligent memory search decision logic")
    print("="*80)

    results = []

    # Run test suites
    results.append(("Hard Reject", test_hard_reject_queries()))
    results.append(("Hard Accept", test_hard_accept_queries()))
    results.append(("Soft Threshold", test_soft_threshold_queries()))
    results.append(("Edge Cases", test_edge_cases()))

    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {test_name}")
        if not passed:
            all_passed = False

    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("\nQuery analysis system is working correctly:")
        print("  • Simple queries skip memory search (performance optimization)")
        print("  • Complex/context-dependent queries trigger search")
        print("  • Mirrors memory filter's worthiness analysis logic")
    else:
        print("❌ SOME TESTS FAILED")
        print("\nReview failed test cases above")
    print("="*80 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
