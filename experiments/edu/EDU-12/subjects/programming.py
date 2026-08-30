"""Block 2 — Programming. Procedure, execution, tools, debugging.

Graded by RUNNING what is produced, not by comparing it to a reference
solution. That is the point of the block: correctness is established by the
world rather than by resemblance to an answer key, so a plausible-looking
program that does not work scores zero.
"""

SUBJECT = "programming"
DESCRIPTION = "Writing, running, and repairing small programs over files and data."
COGNITIVE_DEMAND = ("procedure", "execution", "tool_use", "debugging")
TOOLS = ("run_python", "read_file", "write_file")
ENVIRONMENT = "sandbox"

LESSONS = [
    {"id": "p_l1", "concept": "function_definition",
     "content": "A function takes named inputs and returns a value. Define it with def, name it, list its parameters, and return the result.",
     "example": {"source": "def double(n):\n    return n * 2", "call": "double(4)", "result": 8}},
    {"id": "p_l2", "concept": "iteration",
     "content": "A loop repeats work over each element of a collection, accumulating a result.",
     "example": {"source": "def total(values):\n    t = 0\n    for v in values:\n        t = t + v\n    return t", "call": "total([1,2,3])", "result": 6}},
    {"id": "p_l3", "concept": "conditional_filter",
     "content": "A condition inside a loop keeps only the elements that satisfy a test.",
     "example": {"source": "def evens(values):\n    return [v for v in values if v % 2 == 0]", "call": "evens([1,2,3,4])", "result": [2, 4]}},
    {"id": "p_l4", "concept": "file_io",
     "content": "Read a file's text with open and read. Write text with open in write mode.",
     "example": {"source": "def load(path):\n    with open(path) as f:\n        return f.read()"}},
    {"id": "p_l5", "concept": "json_structure",
     "content": "JSON text parses into dictionaries and lists. Access a dictionary value by its key.",
     "example": {"source": "import json\ndef parse(text):\n    return json.loads(text)", "call": "parse('{\"a\": 1}')", "result": {"a": 1}}},
    {"id": "p_l6", "concept": "debugging",
     "content": "When a program raises an error, read the message, find the named line, and correct the cause rather than the symptom.",
     "example": {"broken": "def half(n):\n    return n / 0", "error": "ZeroDivisionError", "fixed": "def half(n):\n    return n / 2"}},
]

PRETEST = [
    {"id": "p_pre1", "kind": "program", "prompt": "Write a function triple(n) returning n multiplied by three", "entry": "triple", "tests": [{"args": [3], "expected": 9}, {"args": [0], "expected": 0}, {"args": [-2], "expected": -6}]},
    {"id": "p_pre2", "kind": "program", "prompt": "Write a function largest(values) returning the largest number in a list", "entry": "largest", "tests": [{"args": [[3, 9, 2]], "expected": 9}, {"args": [[-5, -1]], "expected": -1}]},
    {"id": "p_pre3", "kind": "program", "prompt": "Write a function count_odd(values) returning how many numbers in a list are odd", "entry": "count_odd", "tests": [{"args": [[1, 2, 3, 4, 5]], "expected": 3}, {"args": [[2, 4]], "expected": 0}]},
    {"id": "p_pre4", "kind": "repair", "prompt": "This function should return the average but raises an error. Repair it", "entry": "average", "broken": "def average(values):\n    return sum(values) / 0", "tests": [{"args": [[2, 4, 6]], "expected": 4.0}]},
    {"id": "p_pre5", "kind": "program", "prompt": "Write a function keys_of(text) returning the sorted keys of a JSON object given as text", "entry": "keys_of", "tests": [{"args": ["{\"b\": 1, \"a\": 2}"], "expected": ["a", "b"]}]},
    {"id": "p_pre6", "kind": "program", "prompt": "Write a function longest(words) returning the longest string in a list", "entry": "longest", "tests": [{"args": [["a", "abc", "ab"]], "expected": "abc"}]},
]

POSTTEST = [
    {"id": "p_post1", "kind": "program", "prompt": "Write a function quadruple(n) returning n multiplied by four", "entry": "quadruple", "tests": [{"args": [3], "expected": 12}, {"args": [-1], "expected": -4}]},
    {"id": "p_post2", "kind": "program", "prompt": "Write a function smallest(values) returning the smallest number in a list", "entry": "smallest", "tests": [{"args": [[8, 2, 5]], "expected": 2}, {"args": [[-3, -9]], "expected": -9}]},
    {"id": "p_post3", "kind": "program", "prompt": "Write a function count_even(values) returning how many numbers in a list are even", "entry": "count_even", "tests": [{"args": [[1, 2, 3, 4]], "expected": 2}, {"args": [[1, 3]], "expected": 0}]},
    {"id": "p_post4", "kind": "repair", "prompt": "This function should return the total but returns the wrong value. Repair it", "entry": "total", "broken": "def total(values):\n    t = 0\n    for v in values:\n        t = v\n    return t", "tests": [{"args": [[1, 2, 3]], "expected": 6}]},
    {"id": "p_post5", "kind": "program", "prompt": "Write a function value_for(text, key) returning the value stored under a key in a JSON object given as text", "entry": "value_for", "tests": [{"args": ["{\"a\": 7}", "a"], "expected": 7}]},
    {"id": "p_post6", "kind": "program", "prompt": "Write a function shortest(words) returning the shortest string in a list", "entry": "shortest", "tests": [{"args": [["abc", "a", "ab"]], "expected": "a"}]},
]

TRANSFER = [
    {"id": "p_tr1", "kind": "program", "composes": ["file_io", "json_structure", "iteration"],
     "prompt": "Write a function summarise(path) that reads a JSON file containing a list of records with amount and customer, and returns a dictionary of total amount per customer",
     "entry": "summarise", "fixture": {"records.json": "[{\"customer\": \"a\", \"amount\": 3}, {\"customer\": \"b\", \"amount\": 5}, {\"customer\": \"a\", \"amount\": 4}]"},
     "tests": [{"args": ["records.json"], "expected": {"a": 7, "b": 5}}]},
    {"id": "p_tr2", "kind": "program", "composes": ["iteration", "conditional_filter"],
     "prompt": "Write a function above_mean(values) returning the values strictly greater than the mean of the list",
     "entry": "above_mean", "tests": [{"args": [[1, 2, 3, 10]], "expected": [10]}, {"args": [[2, 2, 2]], "expected": []}]},
    {"id": "p_tr3", "kind": "program", "composes": ["file_io", "iteration"],
     "prompt": "Write a function line_count(path) that reads a text file and returns the number of non-empty lines",
     "entry": "line_count", "fixture": {"notes.txt": "alpha\n\nbeta\ngamma\n"},
     "tests": [{"args": ["notes.txt"], "expected": 3}]},
    {"id": "p_tr4", "kind": "program", "composes": ["json_structure", "conditional_filter", "file_io"],
     "prompt": "Write a function names_over(path, limit) that reads a JSON file of records with name and score and returns the sorted names whose score exceeds limit",
     "entry": "names_over", "fixture": {"scores.json": "[{\"name\": \"z\", \"score\": 9}, {\"name\": \"y\", \"score\": 2}, {\"name\": \"x\", \"score\": 7}]"},
     "tests": [{"args": ["scores.json", 5], "expected": ["x", "z"]}]},
]
