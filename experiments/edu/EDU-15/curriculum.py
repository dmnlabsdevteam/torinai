#!/usr/bin/env python3
"""The sealed curriculum and exam for EDU-15.

SEALED BEFORE THE TEACHER SEES ANYTHING. The exam lives in this module and is
written before a single lesson runs, so no lesson can be tuned toward it and no
teacher output can leak into it. Grading is by BEHAVIOUR -- hidden input/output
pairs run in the sandbox -- never by resemblance to the teacher's syntax.

`total += x` and `total = total + x` are the same program. A grader that can
tell them apart is measuring imitation, not competence.
"""

from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass(frozen=True)
class Task:
    """One programming task, graded by what its function DOES."""

    task_id: str
    prompt: str
    entry: str                       # function name the solution must define
    #: (args, expected). Hidden from the teacher and from the student.
    tests: Tuple[Tuple[tuple, Any], ...]
    #: Which primitives a correct solution must compose. Recorded, not enforced.
    requires: Tuple[str, ...] = ()


#: The five primitives of session one. Deliberately small: the question is
#: whether procedural COMPOSITION can be acquired, not breadth.
PRIMITIVES = ("VARIABLE", "EXPRESSION", "CONDITIONAL", "LOOP", "FUNCTION")


#: ── COLD PRE-TEST ───────────────────────────────────────────────────────────
#: Run with the teacher detached, before any instruction. Establishes what the
#: substrate can already construct, which is the only baseline that means
#: anything.
PRETEST: List[Task] = [
    Task("pre_double", "Write a function `double` that returns its argument times two.",
         "double", (((2,), 4), ((0,), 0), ((-3,), -6)), ("FUNCTION", "EXPRESSION")),
    Task("pre_is_even", "Write a function `is_even` returning True when its argument is even.",
         "is_even", (((4,), True), ((7,), False), ((0,), True)),
         ("FUNCTION", "CONDITIONAL")),
    Task("pre_sum_list", "Write a function `sum_list` returning the sum of a list of numbers.",
         "sum_list", ((([1, 2, 3],), 6), (([],), 0), (([5],), 5)),
         ("FUNCTION", "LOOP")),
    Task("pre_count_over", "Write a function `count_over` taking a list and a threshold, "
         "returning how many values are strictly greater than the threshold.",
         # Same boundary: an input equal to the threshold separates > from >=.
         "count_over", ((([1, 5, 9], 4), 2), (([], 0), 0), (([1, 2], 10), 0),
                        (([4, 5], 4), 1)),
         ("FUNCTION", "LOOP", "CONDITIONAL")),
]


#: ── TEACHER-OFF EXAM ────────────────────────────────────────────────────────
#: None of these appear in any lesson. C is the discriminating one: no single
#: primitive solves it, so recall cannot pass it -- only composition can.
EXAM: List[Task] = [
    Task("exam_a_average",
         "Write a function `average` that receives three numbers and returns their average.",
         "average", (((3, 3, 3), 3.0), ((1, 2, 3), 2.0), ((0, 0, 0), 0.0),
                     ((-3, 0, 3), 0.0)),
         ("VARIABLE", "EXPRESSION", "FUNCTION")),
    Task("exam_b_sign",
         "Write a function `sign_word` that returns 'positive', 'negative' or 'zero' "
         "for an integer.",
         "sign_word", (((5,), "positive"), ((-5,), "negative"), ((0,), "zero"),
                       ((1,), "positive")),
         ("CONDITIONAL", "FUNCTION")),
    Task("exam_c_total_above_ten",
         "Write a function `total_above_ten` that takes a list of numbers and returns "
         "the sum of only the values greater than 10.",
         # 10 ITSELF IS THE DISCRIMINATING CASE. Without it `>= 10` passes,
         # because no input sits on the boundary the prompt actually names --
         # a solution with the wrong comparison graded as correct. A hidden
         # test set that cannot separate `>` from `>=` is not testing the
         # thing the task asks for.
         "total_above_ten", ((([3, 11, 7, 15, 2],), 26), (([],), 0),
                             (([1, 2, 3],), 0), (([20, 30],), 50),
                             (([10, 10, 11],), 11), (([10],), 0)),
         ("LOOP", "CONDITIONAL", "VARIABLE", "FUNCTION")),
    Task("exam_d_longest",
         "Write a function `longest` that returns the longest string in a list, "
         "or '' for an empty list.",
         "longest", (((["a", "abc", "ab"],), "abc"), (([],), ""),
                     (((["x"]),), "x")),
         ("LOOP", "CONDITIONAL", "VARIABLE", "FUNCTION")),
]


#: ── TEACHER CONTRACT ────────────────────────────────────────────────────────
#: The model may explain and propose. It may not attest. Nothing it says is
#: evidence; only execution is.
TEACHER_CONTRACT = """You are teaching a persistent cognitive substrate basic Python.

Teach ONE concept at a time using a concise explanation, two contrasting
examples, and a counterexample. Ask the student to predict or construct BEFORE
you reveal any correction.

You must not:
- claim the student has learned anything
- treat your own generated output as evidence of what a program does
- state that code is correct; only execution establishes behaviour
- reveal or reference any held-out exam task

When the student fails, name the conceptual gap and give a DISCRIMINATING
example that separates the wrong understanding from the right one. Do not simply
supply the final answer.

Reply with a short lesson, then exactly one exercise for the student to attempt.
"""

LESSONS = [
    ("VARIABLE",    "binding a value to a name, and reading it back"),
    ("EXPRESSION",  "transforming values with arithmetic and comparison operators"),
    ("CONDITIONAL", "choosing behaviour with if/elif/else on a boolean condition"),
    ("LOOP",        "repeating behaviour over a list, accumulating and filtering"),
    ("FUNCTION",    "parameters, return values, and composing earlier concepts"),
]
