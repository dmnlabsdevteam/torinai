"""A registry of correct, canonical algorithm implementations owned by the tools.

Each entry is a real, verified implementation (not a stub and not model output),
keyed by name with common aliases. ``implement_algorithm`` looks an algorithm up
here; an unknown request returns an honest "not in the registry" with the list of
what is available. This is the model-free replacement for asking a model to write
an algorithm: a curated library the substrate can draw on.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# name -> {aliases, time, space, code}
ALGORITHMS: Dict[str, dict] = {
    "quicksort": {
        "aliases": ["quick sort", "quick_sort"],
        "time": "O(n log n) average, O(n^2) worst", "space": "O(log n)",
        "code": '''def quicksort(arr):
    """Quicksort. Time: O(n log n) average, O(n^2) worst. Space: O(log n)."""
    if len(arr) <= 1:
        return list(arr)
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    mid = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + mid + quicksort(right)
''',
    },
    "merge_sort": {
        "aliases": ["mergesort", "merge sort"],
        "time": "O(n log n)", "space": "O(n)",
        "code": '''def merge_sort(arr):
    """Merge sort. Time: O(n log n). Space: O(n)."""
    if len(arr) <= 1:
        return list(arr)
    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result
''',
    },
    "bubble_sort": {
        "aliases": ["bubblesort", "bubble sort"],
        "time": "O(n^2)", "space": "O(1)",
        "code": '''def bubble_sort(arr):
    """Bubble sort. Time: O(n^2). Space: O(1)."""
    a = list(arr)
    n = len(a)
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if a[j] > a[j + 1]:
                a[j], a[j + 1] = a[j + 1], a[j]
                swapped = True
        if not swapped:
            break
    return a
''',
    },
    "insertion_sort": {
        "aliases": ["insertionsort", "insertion sort"],
        "time": "O(n^2)", "space": "O(1)",
        "code": '''def insertion_sort(arr):
    """Insertion sort. Time: O(n^2). Space: O(1)."""
    a = list(arr)
    for i in range(1, len(a)):
        key = a[i]
        j = i - 1
        while j >= 0 and a[j] > key:
            a[j + 1] = a[j]
            j -= 1
        a[j + 1] = key
    return a
''',
    },
    "binary_search": {
        "aliases": ["binarysearch", "binary search"],
        "time": "O(log n)", "space": "O(1)",
        "code": '''def binary_search(arr, target):
    """Binary search on a sorted list. Returns index or -1. Time: O(log n)."""
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
    },
    "linear_search": {
        "aliases": ["linearsearch", "linear search"],
        "time": "O(n)", "space": "O(1)",
        "code": '''def linear_search(arr, target):
    """Linear search. Returns index or -1. Time: O(n)."""
    for i, x in enumerate(arr):
        if x == target:
            return i
    return -1
''',
    },
    "bfs": {
        "aliases": ["breadth first search", "breadth-first search", "breadth_first_search"],
        "time": "O(V + E)", "space": "O(V)",
        "code": '''def bfs(graph, start):
    """Breadth-first traversal. graph: {node: [neighbors]}. Time: O(V + E)."""
    from collections import deque
    visited = [start]
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.append(neighbor)
                queue.append(neighbor)
    return visited
''',
    },
    "dfs": {
        "aliases": ["depth first search", "depth-first search", "depth_first_search"],
        "time": "O(V + E)", "space": "O(V)",
        "code": '''def dfs(graph, start):
    """Depth-first traversal. graph: {node: [neighbors]}. Time: O(V + E)."""
    visited = []
    stack = [start]
    while stack:
        node = stack.pop()
        if node not in visited:
            visited.append(node)
            for neighbor in reversed(graph.get(node, [])):
                if neighbor not in visited:
                    stack.append(neighbor)
    return visited
''',
    },
    "dijkstra": {
        "aliases": ["dijkstras", "dijkstra's shortest path", "shortest path"],
        "time": "O((V + E) log V)", "space": "O(V)",
        "code": '''def dijkstra(graph, start):
    """Dijkstra shortest paths. graph: {node: [(neighbor, weight)]}. Returns {node: dist}."""
    import heapq
    dist = {start: 0}
    pq = [(0, start)]
    while pq:
        d, node = heapq.heappop(pq)
        if d > dist.get(node, float('inf')):
            continue
        for neighbor, weight in graph.get(node, []):
            nd = d + weight
            if nd < dist.get(neighbor, float('inf')):
                dist[neighbor] = nd
                heapq.heappush(pq, (nd, neighbor))
    return dist
''',
    },
    "fibonacci": {
        "aliases": ["fib"],
        "time": "O(n)", "space": "O(1)",
        "code": '''def fibonacci(n):
    """nth Fibonacci number (0-indexed: fib(0)=0). Time: O(n). Space: O(1)."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
''',
    },
    "factorial": {
        "aliases": ["fact"],
        "time": "O(n)", "space": "O(1)",
        "code": '''def factorial(n):
    """n! iteratively. Time: O(n). Space: O(1)."""
    if n < 0:
        raise ValueError("factorial is undefined for negative numbers")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
''',
    },
    "gcd": {
        "aliases": ["greatest common divisor", "euclidean"],
        "time": "O(log min(a, b))", "space": "O(1)",
        "code": '''def gcd(a, b):
    """Greatest common divisor (Euclid). Time: O(log min(a, b))."""
    while b:
        a, b = b, a % b
    return abs(a)
''',
    },
    "is_prime": {
        "aliases": ["prime", "primality"],
        "time": "O(sqrt(n))", "space": "O(1)",
        "code": '''def is_prime(n):
    """Primality test by trial division. Time: O(sqrt(n))."""
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True
''',
    },
    "sieve_of_eratosthenes": {
        "aliases": ["sieve", "eratosthenes", "primes"],
        "time": "O(n log log n)", "space": "O(n)",
        "code": '''def sieve_of_eratosthenes(n):
    """All primes <= n. Time: O(n log log n). Space: O(n)."""
    if n < 2:
        return []
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return [i for i, prime in enumerate(sieve) if prime]
''',
    },
    "two_sum": {
        "aliases": ["two sum", "2sum"],
        "time": "O(n)", "space": "O(n)",
        "code": '''def two_sum(nums, target):
    """Indices of two numbers summing to target, or None. Time: O(n)."""
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return None
''',
    },
    "is_palindrome": {
        "aliases": ["palindrome"],
        "time": "O(n)", "space": "O(1)",
        "code": '''def is_palindrome(s):
    """Whether a sequence reads the same forwards and backwards. Time: O(n)."""
    i, j = 0, len(s) - 1
    while i < j:
        if s[i] != s[j]:
            return False
        i += 1
        j -= 1
    return True
''',
    },
}


def _norm(name: str) -> str:
    cleaned = name.lower().strip().replace("_", " ")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch == " ").strip()


def lookup(name: str) -> Optional[dict]:
    """Find an algorithm by canonical name or alias (case/format-insensitive)."""
    key = _norm(name)
    compact = key.replace(" ", "_")
    for canonical, entry in ALGORITHMS.items():
        if compact == canonical or key == canonical.replace("_", " "):
            return {"name": canonical, **entry}
        for alias in entry.get("aliases", []):
            if key == _norm(alias) or compact == _norm(alias).replace(" ", "_"):
                return {"name": canonical, **entry}
    return None


def available() -> List[str]:
    return sorted(ALGORITHMS)
