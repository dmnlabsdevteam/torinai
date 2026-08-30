"""Block 1 — Mathematics. Abstraction, formal manipulation, composition.

Deliberately NOT relational structure learning. Nothing here is solved by
finding which preconditions gate an action; the operations are numeric and
compositional, which is the substrate's known weakest ground (arithmetic
induction was deferred, not built). A poor result here is a real finding.
"""

SUBJECT = "mathematics"
DESCRIPTION = "Numeric abstraction, sequence rules, ratio, and linear equations."
COGNITIVE_DEMAND = ("abstraction", "formal_manipulation", "composition")
TOOLS = ("calculate",)
ENVIRONMENT = "none"

LESSONS = [
    {"id": "m_l1", "concept": "sequence_difference",
     "content": "A sequence with a constant difference between terms is arithmetic. Find the difference by subtracting any term from the next.",
     "example": {"given": [3, 7, 11, 15], "difference": 4, "next": 19}},
    {"id": "m_l2", "concept": "sequence_ratio",
     "content": "A sequence with a constant ratio between terms is geometric. Find the ratio by dividing a term by the previous one.",
     "example": {"given": [2, 6, 18, 54], "ratio": 3, "next": 162}},
    {"id": "m_l3", "concept": "linear_equation",
     "content": "To solve a x plus b equals c, subtract b from both sides then divide both sides by a.",
     "example": {"equation": "3x + 6 = 21", "step1": "3x = 15", "solution": 5}},
    {"id": "m_l4", "concept": "ratio_comparison",
     "content": "To compare two ratios, cross multiply. The ratio with the larger cross product is greater.",
     "example": {"left": [3, 4], "right": [5, 7], "cross": [21, 20], "greater": "left"}},
    {"id": "m_l5", "concept": "percentage_change",
     "content": "Percentage change is the difference divided by the original value, times one hundred.",
     "example": {"original": 40, "new": 50, "change_percent": 25}},
]

PRETEST = [
    {"id": "m_pre1", "kind": "value", "prompt": "Next term in the sequence 5, 9, 13, 17", "given": [5, 9, 13, 17], "answer": 21},
    {"id": "m_pre2", "kind": "value", "prompt": "Next term in the sequence 3, 9, 27, 81", "given": [3, 9, 27, 81], "answer": 243},
    {"id": "m_pre3", "kind": "value", "prompt": "Solve for x: 4x + 8 = 32", "equation": [4, 8, 32], "answer": 6},
    {"id": "m_pre4", "kind": "choice", "prompt": "Which ratio is greater, 2 to 5 or 3 to 8", "options": ["left", "right"], "left": [2, 5], "right": [3, 8], "answer": "left"},
    {"id": "m_pre5", "kind": "value", "prompt": "A value rises from 20 to 26. What is the percentage change", "original": 20, "new": 26, "answer": 30},
    {"id": "m_pre6", "kind": "value", "prompt": "Next term in the sequence 1, 4, 9, 16", "given": [1, 4, 9, 16], "answer": 25},
]

POSTTEST = [
    {"id": "m_post1", "kind": "value", "prompt": "Next term in the sequence 11, 18, 25, 32", "given": [11, 18, 25, 32], "answer": 39},
    {"id": "m_post2", "kind": "value", "prompt": "Next term in the sequence 4, 12, 36, 108", "given": [4, 12, 36, 108], "answer": 324},
    {"id": "m_post3", "kind": "value", "prompt": "Solve for x: 7x + 5 = 54", "equation": [7, 5, 54], "answer": 7},
    {"id": "m_post4", "kind": "choice", "prompt": "Which ratio is greater, 5 to 9 or 6 to 11", "options": ["left", "right"], "left": [5, 9], "right": [6, 11], "answer": "left"},
    {"id": "m_post5", "kind": "value", "prompt": "A value falls from 80 to 60. What is the percentage change", "original": 80, "new": 60, "answer": -25},
    {"id": "m_post6", "kind": "value", "prompt": "Solve for x: 2x + 19 = 7", "equation": [2, 19, 7], "answer": -6},
]

TRANSFER = [
    {"id": "m_tr1", "kind": "value", "composes": ["sequence_difference", "linear_equation"],
     "prompt": "In the sequence 6, 10, 14, 18 the term at position n is a n plus b. Solve for the term at position 9",
     "given": [6, 10, 14, 18], "position": 9, "answer": 38},
    {"id": "m_tr2", "kind": "value", "composes": ["sequence_ratio", "percentage_change"],
     "prompt": "A geometric sequence starts 5, 10, 20. What is the percentage change from the third term to the fourth",
     "given": [5, 10, 20], "answer": 100},
    {"id": "m_tr3", "kind": "choice", "composes": ["ratio_comparison", "percentage_change"],
     "prompt": "Value A rises 12 to 15, value B rises 20 to 24. Which had the greater percentage change",
     "options": ["left", "right"], "left": [12, 15], "right": [20, 24], "answer": "left"},
    {"id": "m_tr4", "kind": "value", "composes": ["sequence_difference", "sequence_ratio"],
     "prompt": "The differences of the sequence 2, 5, 11, 23 form their own sequence. What is the next term of the original",
     "given": [2, 5, 11, 23], "answer": 47},
]
