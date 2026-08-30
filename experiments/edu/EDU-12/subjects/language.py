"""Block 4 — Language and knowledge. Concepts, relations, reading, explanation.

The block where a substrate without a language model is expected to be weakest
on open comprehension and strongest on structured semantic relations, because
taxonomy and part-whole reasoning are transitive closure over stored relations,
which the substrate does natively, while paraphrase is not.

That split is the interesting measurement. It should NOT be smoothed over: an
honest failure on open comprehension with a strong result on relational
semantics says something specific about what has migrated into the substrate.
"""

SUBJECT = "language"
DESCRIPTION = "Semantic relations, definitions, and reading for stated fact."
COGNITIVE_DEMAND = ("concepts", "semantic_relations", "reading", "explanation")
TOOLS = ("lookup_concept",)
ENVIRONMENT = "none"

LESSONS = [
    {"id": "l_l1", "concept": "is_a_transitivity",
     "content": "If one thing is a kind of a second, and the second is a kind of a third, then the first is a kind of the third.",
     "example": {"facts": ["sparrow is_a bird", "bird is_a animal"], "follows": "sparrow is_a animal"}},
    {"id": "l_l2", "concept": "part_of",
     "content": "A part belongs to a whole. Parts of a part are parts of the whole.",
     "example": {"facts": ["wheel part_of car", "tyre part_of wheel"], "follows": "tyre part_of car"}},
    {"id": "l_l3", "concept": "antonym",
     "content": "An antonym is a word with the opposite meaning along one dimension.",
     "example": {"pairs": [["hot", "cold"], ["fast", "slow"]]}},
    {"id": "l_l4", "concept": "definition_by_genus_and_difference",
     "content": "A definition names the general category a thing belongs to, then what distinguishes it from others in that category.",
     "example": {"term": "island", "genus": "land", "difference": "surrounded by water"}},
    {"id": "l_l5", "concept": "stated_versus_implied",
     "content": "A passage states some things directly and leaves others unstated. Only what is stated or strictly follows can be asserted.",
     "example": {"passage": "The vault is locked. Only the warden holds a key.", "stated": "the vault is locked", "not_stated": "the warden opened it"}},
]

PRETEST = [
    {"id": "l_pre1", "kind": "choice", "prompt": "Is a robin an animal?",
     "options": ["yes", "no", "undetermined"], "facts": ["A robin is a bird", "A bird is an animal"], "answer": "yes"},
    {"id": "l_pre2", "kind": "choice", "prompt": "Is a piston a car part?",
     "options": ["yes", "no", "undetermined"], "facts": ["A piston is an engine part", "An engine is a car part"], "answer": "yes"},
    {"id": "l_pre3", "kind": "choice", "prompt": "Is a whale a fish?",
     "options": ["yes", "no", "undetermined"], "facts": ["A whale is a mammal", "A shark is a fish"], "answer": "undetermined"},
    {"id": "l_pre4", "kind": "value", "prompt": "What is the opposite of ascend", "answer": "descend"},
    {"id": "l_pre5", "kind": "choice", "prompt": "The passage says the gate is shut and only the keeper has a key. Does the passage state the keeper opened the gate",
     "options": ["yes", "no"], "passage": "The gate is shut. Only the keeper has a key.", "answer": "no"},
    {"id": "l_pre6", "kind": "value", "prompt": "Name the general category in the definition, an island is land surrounded by water", "answer": "land"},
]

POSTTEST = [
    {"id": "l_post1", "kind": "choice", "prompt": "Is an oak a plant?",
     "options": ["yes", "no", "undetermined"], "facts": ["An oak is a tree", "A tree is a plant"], "answer": "yes"},
    {"id": "l_post2", "kind": "choice", "prompt": "Is a key a door part?",
     "options": ["yes", "no", "undetermined"], "facts": ["A key is a lock part", "A lock is a door part"], "answer": "yes"},
    {"id": "l_post3", "kind": "choice", "prompt": "Is a cedar a fish?",
     "options": ["yes", "no", "undetermined"], "facts": ["A cedar is a tree", "A salmon is a fish"], "answer": "undetermined"},
    {"id": "l_post4", "kind": "value", "prompt": "What is the opposite of expand", "answer": "contract"},
    {"id": "l_post5", "kind": "choice", "prompt": "The passage says the ledger is sealed and only the clerk may sign. Does the passage state the clerk signed",
     "options": ["yes", "no"], "passage": "The ledger is sealed. Only the clerk may sign.", "answer": "no"},
    {"id": "l_post6", "kind": "value", "prompt": "Name the general category in the definition, a peninsula is land surrounded by water on three sides", "answer": "land"},
]

TRANSFER = [
    {"id": "l_tr1", "kind": "choice", "composes": ["is_a_transitivity", "part_of"],
     "prompt": "A rotor is part of a turbine, a turbine is part of a generator, and a generator is a machine. Is a rotor part of a machine",
     "options": ["yes", "no", "undetermined"],
     "facts": ["rotor part_of turbine", "turbine part_of generator", "generator is_a machine"],
     "query": ["rotor", "part_of", "machine"], "answer": "yes"},
    {"id": "l_tr2", "kind": "choice", "composes": ["is_a_transitivity", "stated_versus_implied"],
     "prompt": "The passage says every auditor is an inspector and every inspector may enter. Does it state that an auditor may enter",
     "options": ["yes", "no"], "facts": ["auditor is_a inspector"],
     "passage": "Every auditor is an inspector. Every inspector may enter.", "answer": "yes"},
    {"id": "l_tr3", "kind": "choice", "composes": ["stated_versus_implied", "part_of"],
     "prompt": "The passage says the hull is part of the vessel and the vessel was inspected. Does it state the hull was inspected",
     "options": ["yes", "no", "undetermined"],
     "passage": "The hull is part of the vessel. The vessel was inspected.", "answer": "undetermined"},
    {"id": "l_tr4", "kind": "value", "composes": ["definition_by_genus_and_difference", "antonym"],
     "prompt": "In the definition, a valley is land lying lower than the surrounding area, give the opposite of the distinguishing word lower", "answer": "higher"},
]
