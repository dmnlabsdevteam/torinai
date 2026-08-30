# Memory, Semantics and Conversation

**Verified 2026-08-24 against the live system on port 5433.** Every count and
behaviour here was measured, not recalled. Where something is broken it says so
and names the line.

## Standing rules

These apply to everything in this document and to every fix made against it.

**No stubs.** A method either does the thing or raises `NotImplementedError`
naming what is missing and who owns it. A method that returns a plausible value
it did not compute is worse than one that is absent, because absence is
visible.

**No workarounds.** If a caller reads a field that does not exist, fix the
caller or the field — do not add the field as an alias. If a component is
bypassed, route to it — do not duplicate it. Every workaround becomes a second
authority, and two authorities disagree eventually.

**No false positives, no false negatives.** A check that cannot fail is not a
check. A gate whose exception handler returns "nothing found" reports a healthy
system when it is broken. Where something cannot be determined, say so — three
answers (`yes` / `no` / `cannot tell`), never two.

**Absence is not a result.** `0`, `[]`, `None` and `False` must never stand in
for "not measured". Most defects in this document are one value doing both jobs.

**Measured, not asserted.** Every claim here carries the measurement that
produced it. A number without a measurement behind it does not belong in this
file.

This replaces `AGENT_BASED_MEMORY_ARCHITECTURE.md`, which describes an R2
Cloudflare Worker agent and a MySQL query agent. Neither exists — 0 files. MySQL
is retired; the only two `mysql_memory` references left in the codebase are
comments recording its removal.

---

## The one thing to hold onto

**The substrate is the system. The model is a helper it may call.**

Two volition paths run side by side, and only one of them uses prompts:

| path | driven by | what happens with no model |
|---|---|---|
| substrate | tiers, playbooks, findings, facts, rules | runs |
| teacher | prompts | skipped |

`_singleton_thinking_cycle` — the one that builds `"You are between tasks…"` —
opens with `if not self.llm: return`. Beside it sit ten `_idle_*_work` methods
(security, health, system review "deterministic, no LLM", knowledge refresh,
self-improvement, domain expansion, meta-learning, abstraction, memory) that
take **findings and state**, not prompts.

So prompts are how the *helper* is addressed. They were never how the substrate
is addressed. Any design that treats a prompt as the substrate's interface is
wrong, and several places still do — see [Open defects](#open-defects).

---

## Who is what

Read this before reading a file header. **Several headers are stale and
misdescribe their own file** — that is itself one of the defects below.

| component | what it is | evidence |
|---|---|---|
| `autonomous_coordinator` | **the orchestra.** Nothing happens without it. | 10,738 lines; `AutonomousCoordinator` itself declares 133 methods. `main.py` hands it learning, ASI self-improvement, intelligence, governance, health, recovery, proof engine, agent coordinator, research. |
| the substrate | knowledge and inference, spread across four folders | `semantics` (language), `reasoning` (inference, planning, Z3), `learning` (induction, grounding, authority), `domain` (concepts, transfer) |
| `unified_llm` | **the inference service** — one model, one queue, one place where device, timeout, prompts and logging live | Owns the runtime: attaches to a running `llama-server` or loads the GGUF in-process (*"a 25GB model loaded twice does not fit on this machine"*). Every call becomes an `_InferenceJob`; the single `_inference_worker` is *"the ONLY code that ever touches the Llama object"*, so the loop stays free for tool calls while the GPU is busy. `InferenceSpeedTracker` keeps an EWMA of tokens/sec for dynamic timeouts. **Its file header describes only the model and is stale** — see defect 08. |
| the model | a reference the coordinator holds and may consult | `coordinator.py:446` — `self.llm = self.config.get("llm_brain")  # Torin will pass itself`, above the comment *"Its absence is a normal operating state, not a degraded one."* |

**The model is not the brain.** Before the substrate-first change it was the
centre of the architecture; `llm_brain` is now a slot Torin passes *itself* into.
Anything still written as if the model were the centre is legacy, not design.

### One faculty per job

The intended shape is one system per faculty, as a mind has one memory and one
language centre — the coordinator *drives* faculties, it does not contain them.

    memory      core/agents/memory_agent.py     one system
    language    core/semantics/                 one system
    learning    core/learning/                  one system
    security    core/security/                  one system (not a mind's, but required here)

`conversation.py` is therefore **correct as its own file** — it is the single
language faculty, not a fragment of one. The coordinator already treats it that
way (`autonomous_coordinator.py:7130`):

> *"DELEGATED, NOT DECIDED HERE. This used to ask a model directly while
> `Conversation.is_question` asked a rule, and the two disagreed — a plain
> statement was classified as a question and filed in memory as one. Whether a
> sentence asks is a fact about the sentence, and the component that reads
> sentences owns it."*

What **is** fragmented is that faculty's *state* — see defect 07.

---

## Four stores, and they do not talk to each other

This is the fact that causes the most confusion, so it goes first.

| store | holds | rows | read by |
|---|---|---|---|
| `memory_hot` / `memory_cold` | **episodes** — what happened | 880 / 150 | memory search |
| `unified.concepts` + `concept_relations` | **things and how they relate** | 1,178 / 3,128 | grounding, `conversation.resolve` |
| `unified.learned_rules` (+ evidence) | **laws** — if this, then that | 12 / 69 | `rule_grounding` → planner |
| `data/lexicon.json` | **what a word is** | 47 (46 confirmed, 1 refuted) | the reader |

`memory_agent.py` contains **zero references** to concepts, rules, or the
lexicon. Nothing joins an episode to a concept in either direction.

    memory   = "I remember doing this before"
    concepts = "I know what this is"
    rules    = "I know how this behaves"
    lexicon  = "I know what this word means"

Teaching the substrate English changes the **lexicon**, and will not appear in
memory search or change anything the model sees. That is the point of the
model-optional direction, not a gap.

---

## Memory

### What the memory agent is

`core/agents/memory_agent.py` (3,835 lines). Two jobs: **write things down**,
and **find them again**.

Contents right now, by type:

    meta        396    notes about its own thinking
    semantic    220    "this is true"
    episodic    193    "this happened"
    procedural   71    "this is how you do it"

Retrieval is by **meaning**, not keyword — `search_memories` runs an embedding
search. Housekeeping is real: hot→cold tiering, duplicate consolidation, access
counts, importance decay, `supersede` when something newer contradicts.

### `core/memory/` layout

    __init__.py                        116
    live_recall.py                     344    recall running alongside a conversation
    query/postgres_query_agent.py      485    the query agent that actually exists
    storage/postgres_storage.py      1,458    the store
    utils/embedding_service.py         358    vectors (a model boundary — see below)
    utils/interfaces.py                410
    utils/memory_filter.py             533    worthiness + exemption — see below
    utils/memory_injection_policy.py   257    ONE policy: "should memory enter, and what kind"
    utils/memory_injector.py           450    retrieve → format → place
    utils/memory_worthiness.py         329    the metadata worthiness is judged on

### Who asks memory for things

Two consumers, for different reasons:

1. **`neural_bridge`** (`neural_bridge.py:1926`) — the real one. During
   reasoning it searches memory and inserts the result into `request.context`,
   which substrate reasoning consumes. **Verified live**: a request with
   `cached_memories = None` triggers exactly 1 search; with `[]`, exactly 0.
2. **`general_purpose_executor`** — searches at task start and pastes the
   result into the initial user message (`previous_context`, consumed once at
   line 1968).

`embedding_service.generate_embedding` is a **model boundary**. Under
`STRICT_MODEL_FREE` it refuses by name, so memory *storage* succeeds while the
episode is not retained. That is correct behaviour and it is visible in the
transcript, not silent.

### What gets kept — worthiness, and what bypasses it

`memory_filter.py` (533) and `memory_worthiness.py` (329) decide what is worth
storing at all. Read this before assuming a memory was dropped.

**Worthiness asks:** is this novel, deeply reasoned, cross-domain, high
consequence? Hard-store on strategic decisions, 5+ reasoning steps, 3+
inference depth, cross-domain synthesis, novel knowledge. Hard-reject on
trivial factual lookups with <2 steps, simple calculations under 0.3
complexity, and no-reusability-plus-low-consequence. It is O(1) — enum checks
and counters, no embeddings. Thresholds live in
`config/memory_filtering_policy.json`.

**But records bypass it entirely.** `MemoryFilter.exemption_for(tags,
raw_event)` returns a reason, and any memory carrying `raw_event["event"]` — or
one of twelve `EXEMPT_EVENT_TAGS` (task outcomes, safety events, governance
decisions, learning updates, mapping verdicts, critical failures) — skips
worthiness and is stored with `rule_matched="event_class_exemption"`.

The reason is a defect that actually happened, recorded at `memory_agent.py:442`:

> *"Observations are measurements, not insights. The worthiness filter asks 'is
> this novel / deeply reasoned / cross-domain enough to keep?' — the wrong
> question for a data point. Applied to task outcomes it produced
> **survivorship bias**: failures (importance 0.9 → high consequence) were
> retained while successes (0.7) were discarded, so the measured success_rate
> could never rise above near-zero no matter how the system actually
> performed."*

    worthiness   judges CANDIDATES for retention — is this worth keeping?
    exemption    admits RECORDS — things whose value is that they happened

**Teaching is a record, and is already exempt.** `cognitive_ingress` stores each
admitted proposition with `raw_event={"event": "proposition_admitted", …}`, so
it bypasses worthiness. Verified: six teaching memories in the store, all tagged
`["language","admitted_proposition"]`, all persisted.

This matters because teaching is structurally identical to what the filter was
built to reject — short, factual, one reasoning step, low complexity. Judged on
worthiness it *would* be rejected: a hand-built metadata object of that shape
evaluates to `should_store = False`. The exemption is what stops the filter
eating the substrate's own records, and **exemption is decided in one place**
so the memory agent cannot carry a second copy of the policy that drifts.

---

## Semantics — the language faculty

`core/semantics/`, 2,835 lines. It turns English into things the substrate can
hold, and turns what it holds back into English. Each file owns one step.

**Sentence → claim**

| file | lines | job |
|---|---|---|
| `sentence_machine.py` | 177 | the machine a reading runs on: cursor, registers, comparator. Not a parser — a small computer. |
| `derived_reader.py` | 316 | **derives** the reading procedure from sentence/meaning pairs. EDU-13: 7/7 held-out sentences, every content word new, **0 model calls**. |
| `reading_registry.py` | 97 | holds derived procedures for reuse |
| `claim_shape.py` | 169 | separates *what is claimed* from *how it is worded* |

`claim_shape` exists because of a measurement, not a preference:

    0.948   "the vault is locked"  vs  "the vault is not locked"
    0.484   "the vault is locked"  vs  "the safe is secured"

A statement and its negation are nearly identical to an embedding; two
phrasings of the same thing are half as alike. **No threshold recovers
polarity, and a bigger model makes it worse.** So polarity and tense are read
when the memory is *written* and stored beside it.

**Words**

| file | lines | job |
|---|---|---|
| `lexicon.py` | 147 | what class a word is, and where that claim came from. **Empty.** |
| `class_induction.py` | 210 | induces a *rule* for a class from confirmed words |
| `lexical_normalization.py` | 275 | one canonical form per surface word, every path |

`class_induction` answers a real failure: *EDU-16 taught nine words, confirmed
all nine against the world, and classified none of nine held-out words —
because nothing could be applied to a word never seen.* A rule is kept only if
it is right about every confirmed example of its class and wrong about none of
the others. Where no feature separates two classes (`cold` vs `tank`) it
reports UNDECIDED rather than guessing.

`lexical_normalization` owns **two readings**, because identity and retrieval
have opposite failure modes:

    canonical_term(x)   IDENTITY   strict — used by cognitive_ingress.
                                   Over-merging fuses two concepts permanently.
    match_key(x)        RETRIEVAL  loose — used by conversation.stem and
                                   tool_discovery._stem. A miss means the
                                   substrate cannot find what it knows.

Measured on all 1,178 concepts: identity **0 collisions**, retrieval **2**
(`fuzz_test`/`fuzz_testing`, `mutation_test`/`mutation_testing`) — exactly the
merging retrieval wants.

**The door**

`cognitive_ingress.py` (455) — the single door all knowledge enters through,
with provenance. `admit(proposition, surface, provenance)` and
`admit_relation(subject, relation, object, ...)`.

---

## Conversation

`core/semantics/conversation.py` (978 lines). **This is the substrate's
natural-language interface.** You can talk to it with the model provably
blocked — verified under `STRICT_MODEL_FREE`:

    YOU: a kestrel is a bird      → learned: kestrel, stored=True
    YOU: a kestrel is not a fish  → learned: kestrel, stored=True
    YOU: what is a kestrel        → "kestrel (conversation): met in use…"

The limit is **not** that it cannot be talked to. It is that it only
understands words it has learned.

### `understand(sentence)` — processes incoming words

1. **About this conversation?** answered from the turn record, not the world
2. **Fire recall** — wave 1 goes out *first*, so memory searches during the
   rest of the work rather than after it
3. **Subject** — what continuity hangs on across topic changes
4. **Told, not asked → `teach()`** — store *before* answering, so the reply is
   made from a store that already contains what was just said
5. **`resolve()`** — phrases → concepts it holds
6. **Wave 2** — what the words turned out to *be* is a better query than the
   words were
7. **Asked + unplaced → `look_up()`** — one thing, the longest unresolved phrase
8. **`asked()`** — the relation actually being asked about
9. **`read()`** — derived reader, sentence → claim
10. **`harvest()`** — collect what recall found

Returns an `Understanding`: resolved, reading, answers, acquired, remembered.

### `say(understanding)` — produces the response

*"A reply assembled from what was found, and nothing else."* No generation.
Assembly, in priority order:

- **Contradiction first** — *"I have the opposite on record: …"*, deliberately
  before every early return
- **What changed** — *"Noted — kestrel: is_a bird"*
- **What it remembered**
- **What it does not know** — held to the end, as a real question back to you

It distinguishes *"I don't know"* from *"I looked and found nothing"*.

---

## How a sentence actually flows

    you type
       │
       ▼
    Conversation.understand()
       ├─ classify()          statement or question
       ├─ teach()  ──────────► derived_reader.read() ──► ('kestrel','bird','affirms')
       │                            │
       │                            ▼
       │                       cognitive_ingress.admit_relation()
       │                            │  normalize_term → canonical_term
       │                            ▼
       │                       unified.concepts + concept_relations
       ├─ resolve()  ◄──────── reads those concepts back
       ├─ recall()   ◄──────── memory_agent.search_memories()  (embeddings)
       └─ asked()             the relation being asked about
       │
       ▼
    say()  ──► text, assembled from what was found

Nothing in that path requires a model. `look_up()` may call one to research an
unknown word, and it is optional.

---

## Entry points — external vs internal

These are **two different things** and must not share a path.

| | arrives | trust | scheduling |
|---|---|---|---|
| **external** | a person or another system speaks | untrusted — needs auth | queued |
| **internal** | a subsystem calls the substrate mid-work | already inside the boundary | already scheduled |

Internal callers are the idle tiers, the executor, and `neural_bridge` asking
for coverage. Putting them through the external door would put authentication
and queueing in front of the system's own thinking.

### The external authority already exists

`AutonomousCoordinator.handle_user_request()` (`autonomous_coordinator.py:7051`)
is the entry-point authority, and it already has the right shape:

    kind = await self._request_kind(message)        → delegates to Conversation
    if kind in ("question", "telling"):
        answered = await self._answer_from_what_is_held(message)   → substrate
        if answered is not None:
            return answered
    … otherwise it becomes a Task

Its docstring records the failure that produced it:

> *"Everything used to become a Task. Asking 'What is a load balancer?'
> therefore got the full autonomous-work machinery: 84 tools selected and
> ranked (no research tool anywhere), 31,137 of a 32,768-token window went to
> tool schemas, a Bayesian budget granted 26 iterations over 4,680 seconds, and
> the first thing it did was create a directory. The model's own reasoning said
> 'I don't need to run any tools to answer this conceptually, but per my
> instructions, I should.' Measured, in the live system. **A question is not a
> job and must not be costed like one.**"*

### But four surfaces sit in front of it

| surface | routes | reaches the substrate |
|---|---|---|
| `chat_server.py` | 5 | partly — knows the authority, still has model-direct paths |
| `companion_server.py` | 2 | **no** |
| `external_api_server.py` | 4 | **no** |
| `thinking_state_api.py` | 4 | **no** |

**Target: delete these paths, leave one external door in front of
`handle_user_request`.** The consolidation has already started —
`chat_server.py:208` records a route being *removed* for exactly this reason:

> *"That is unauthenticated remote task injection with the substrate's own tool
> and safety authority. It was added before auth existed, which is exactly the
> failure mode this codebase keeps producing: **endpoints are open by default
> and closed only if someone remembers.** The capability itself is sound and
> stays where it belongs: `AutonomousCoordinator.handle_user_request()`."*

### Two things to check before deleting

1. **What the queue guarantees.** The task queue and `_inference_queue` are
   different mechanisms with different properties. Which one backs the external
   door has not been established.
2. **The R1 companion contract.** `companion_server` speaks a wire format the
   device parses (`data:` lines with a `type` field; `thinking` carries no text
   on purpose, so "considered" stays distinguishable from "concluded"). And
   `/v1/chat/completions` is deliberately llama-server-shaped so the companion
   becomes a base-URL change rather than a rewrite. One door must speak this or
   the device stops working.

### The model is reached from inside, not from the front

`unified_llm` should be reachable only by:

- `neural_bridge` — when `_substrate_first` cannot represent the input
- `llm_teacher` — teaching, gated by `TeacherPolicy`
- tools that use a model *as a tool* (code generation, documentation)

Measured today: **18 of 30 files that import `unified_llm` have zero
substrate-first references.** Three of them are the doors a human speaks
through.

### What the router does

When the substrate cannot settle a request itself, `ReasoningRouter.select_mode`
decides *how* to think — and learns which way works:

1. builds a signature from structural signals (formal criteria, cross-domain,
   abstract)
2. assembles candidate modes from those features — formal criteria →
   `SYMBOLIC` + `HYBRID`; cross-domain → `CROSS_DOMAIN` + `NEURO_SYMBOLIC`
3. ranks them by measured history per archetype: `uses`, `successes`,
   `success_rate`, `avg_confidence`, `avg_cost`, `avg_entropy_delta`,
   `escalations`, from a neutral 0.5 prior
4. returns a **ladder**, which `reason()` walks with escalation — stopping on
   sufficient confidence, sufficient entropy reduction, or spent cost budget
5. consults a small model classification only when ambiguous *and* complex

It is a bandit over reasoning strategies. `_substrate_first` asks *can I answer
this myself*; the router asks *which machinery answers best per unit cost*.

---

## Open defects

Each verified on 2026-08-24. Fix these before building on the memory path.

**1. The coordinator's memory path is dead.**
`autonomous_coordinator.py:2595` reads
`getattr(injected,'formatted_context') or getattr(injected,'content')`.
`InjectedMemories` has neither — its fields are `formatted_text`, `memory_ids`,
`total_memories`, `total_tokens`, `injection_mode`, `retrieval_time`,
`formatting_time`, `timestamp`. Both return `None`, so the method logs
"retrieval returned nothing" and returns `None` **every time**.

**2. RESOLVED 2026-08-24 — recall handed back documents, not claims.** The
diagnosis below is partly wrong and the correction is recorded in *Defect 2* near
the end: storage was never the problem, the record keeps its `reasoning_trace`,
and the fix was to store and prefer the CONCLUSION. Original entry kept for the
reasoning it contains.
`InjectionMode` is OpenAI's chat roles — `system_prompt`, `user_context`,
`assistant_context`, `combined`. Templates emit second-person prose (*"You have
access to the following relevant context from memory:"*). `InjectedMemories`
carries **`formatted_text: str` and no structured records**.

Consequence, measured:

    context as the injector produces it (prose blob)
      formalize → succeeded=False  premises=[]

    context as one fact per item
      formalize → succeeded=True   premises=['pump_hot','pump_loud']

The bridge inserts that blob into `request.context`; the formalizer takes it as
one premise, fails, and the substrate reasons with **zero** premises. It does
not error — it behaves exactly as if no memory was found.

**3. RESOLVED 2026-08-24 — the executor held reasoning machinery it never used.**
See *Defect 3* near the end. Not a double fetch: the retrieval feeds the
executor's own prompt. What was dead was `self.neural_bridge` and
`cached_memories`, plus a start-up log claiming traces were being captured.
`general_purpose_executor.py:1617` declares `cached_memories` with the comment
*"for passing to neural bridge (prevents double-fetching)"*. AST proof: stored
at lines 1617 and 1685, **loaded NEVER**. `ReasoningRequest.cached_memories`
exists and the bridge honours it, so the wire was designed and never connected.

**4. RESOLVED 2026-08-24 — the lexicon was empty; 47 attested entries promoted.**
EDU-16 works — `0/18` before, `18/18` with the teacher, **`18/18` with the
model blocked**, 12/12 sentences, 6/6 transfer, 0 model calls in the exam,
`false_confidence: 0`. Both runs wrote to their own files —
`data/lexicon_edu16.json` and `data/lexicon_scaled.json` — and called `.clear()`
first, so the live `data/lexicon.json` did not exist.

**47 entries are now promoted** from `lexicon_edu16.json`: 46 confirmed, 1
refuted-and-retained. Verified loading: `class_of('belt')` → NOUN,
`class_of('heavy')` → ADJECTIVE, `class_of('blocks')` → **None** (refuted, so
the reader refuses to rely on it).

**The 1,326 from `lexicon_scaled.json` were NOT promoted, and must not be.**
They are confirmed by POSITION — *"seen as subject"* (777), *"seen as verb"*
(317), *"seen as property"* (232) — while the lexicon's own rule is that a class
is confirmed only when **a sentence that depends on it reads**. Nothing in that
file was tested.

The two files overlap on 43 words and disagree on exactly one, which decides it:

    blocks   attested file:  NOUN — then a teacher proposed VERB, and neither
                             "the pump blocks water" nor "the valve blocks air"
                             read, so the entry went REFUTED and was kept
             positional file: VERB, confirmed

The one case where the weaker method can be checked, it produced the class the
world had already refused. Promoting those entries would import a
confirmation-manufacturing method — a false positive at scale, straight into
the store.

Caveat: reading works the same with or without the lexicon today. `a kestrel is
a bird` reads correctly with `kestrel` unknown, because the derived reader works
over classes from the sentence machine's own closed set. The lexicon matters
where classes disambiguate, which is what `class_induction` exists to extend.
This is a prerequisite met, not yet a visible capability gain.

**5. RESOLVED 2026-08-24 — answering now uses what was just stored.**
Told `a kestrel is a bird`, then asked `is a kestrel a bird`, it replied with an
unrelated stored note about arctic terns. It matched on *"bird"* and recited.
Step 8 (`asked()`) does not turn a yes/no question into a check against the
edge admitted seconds earlier. **The gap is in answering, not in reading or
speaking.**

**6. RESOLVED 2026-08-24 — `classify()` misread statements.**
`classify("a kestrel is a bird")` returned **`job`**. It now returns `telling`.
Fixed indirectly: `classify` consults resolution, which was returning zero
relations for every taught concept (defect 5a), so a statement about something
the substrate held looked like a statement about nothing. Verified:

    "a kestrel is a bird"        → telling
    "is a kestrel a bird"        → question
    "fix the pump"               → job
    "what causes pressure loss"  → question

**7. RESOLVED 2026-08-24 — conversation state is now held per session.**
`Conversation` holds `_turns`, `_last_subject`, `_last_reply` and `_recall` —
everything continuity depends on. The coordinator constructs a **fresh instance
at every call site**: `autonomous_coordinator.py:7142` builds one to
`classify(message)`, and `:7156` builds *another* to `understand(message)` — two
instances for the same message. There is no singleton and no accessor.

So the turn record can never accumulate. It cannot carry a subject across turns,
notice a follow-up, or answer "what were we talking about" — the machinery for
all three exists in `conversation.py` and is unreachable. Every message arrives
as if it were the first.

The faculty is not fragmented; its **state** was.

`get_conversation(session)` now holds one conversation per thread of talk,
bounded at `MAX_HELD_CONVERSATIONS = 64` with least-recently-used eviction.
**Deliberately not a global singleton** — one shared instance would merge every
speaker's turns into a single thread, so one person's words would surface as
another's context, which is worse than no continuity. The coordinator threads
one session through both halves of a turn, taken from `conversation_id` /
`session_id` in metadata, falling back to a source-scoped key rather than a
shared constant.

Verified, model blocked:

    YOU:   a harrier is a hawk         →  Noted — harrier: is hawk
    YOU:   is a harrier a hawk         →  Yes — harrier is hawk.
    YOU:   what were we talking about  →  We were talking about harrier.

    turn record: 3 turns, subject 'harrier' carried across all three


**8. File headers misdescribe their files.**
`unified_llm.py` opens with *"Local Qwen 2.5-VL 32B vision-language model
integration via llama-cpp-python"*, which describes one input to the file rather
than the file. What it actually is: a **serialized inference service** — model
runtime (remote server or in-process GGUF), a single-worker GPU queue, EWMA speed
tracking with dynamic timeouts, agent system prompts, and request logging.

`generate()` was separately fixed: it used to short-circuit to `_remote_chat` and
only fall through to `process_request()` when remote was off, so the service had
two parallel implementations and a capability taught to one was missing from the
other. Backend selection now lives in one place beneath both entry points. That
is an internal consolidation, **not** what the service is — describing the whole
file by that one method is the same error as trusting the header.

**Read the code, not the docstring.** Where a header conflicts with the body,
the body is the system.

**9. RESOLVED 2026-08-24 — see *Defect 9* near the end.** `say()` re-derived a
reply that `understand()` had already established from the record, over an empty
result, and produced a worse one.
`understand()` returns early for a self-referential question and sets `.reply`
from `_from_the_record()`. A caller that instead calls `say(understanding)` gets
the reply recomputed from resolved parts — *"There was nothing in that I could
resolve"* where `.reply` holds *"We were talking about harrier."* Two ways to
get one answer, and they disagree. Not fixed.

### Defect 10 — the internal substrate path stops one stage short

**Measured 2026-08-24, by running it, not by reading it.** The internal path is
planning → execution: a goal with state conditions, planned over learned rules,
executed deterministically with no model. Six stages. Five complete.

| # | Stage | Result |
|---|---|---|
| 1 | `coordinator.extract_state_conditions(description)` | `['AT(z, VAULT)', 'AT(z, HALL)']` — wired at `autonomous_coordinator.py:1367` |
| 2 | `ground_for_problem` over the 5 validated rules | 4 operators grounded |
| 3 | `plan_for_state_goal` | `PLAN_FOUND`, 2 steps: `MOVE(z,HALL,LAB)`, `MOVE(z,LAB,VAULT)` |
| 4 | `state_plan_to_tasks` | 2 tasks, each carrying `learned_rule_id=rule_edbe5a8b4ad8` + `grounded_operator` |
| 5 | `executor._try_substrate_execution` | **fires**, re-establishes rule authority, then **refuses** |
| 6 | deterministic execution | never reached |

The refusal, verbatim:

    no tool bound to MOVE in domain 'kite17'

**The gate is right to refuse.** It re-checked the rule against the store, found
it still validated, matched the operator to the rule's action, bound the
variables — and then had nothing to act *with*. It failed closed. It did not
fall through to the model, which is the property the path exists to have.

**The cause is a missing supplier, the same shape as the last one.**
`get_binding_registry()._bindings` holds **0 domains in a live process**. One
production registrar exists — `SentenceMachine.register()` at
`core/semantics/sentence_machine.py:170` — and it has **zero callers**. Every
other `register()` call in the repo is in `tests/` or `experiments/`, which is
why the substrate execution tests pass while production has never executed a
single grounded operator.

So EDU proved the capability with a world the test supplied. Production has the
rules, the planner, the tasks, the provenance and the gate — and no world.

**This is why 0 decisions in the whole record carry a grounded operator.** Not
because the gate never fires; it fires and refuses, silently, at `logger.info`.

### Where the domain system sits — and why it is not the missing piece

**There are three separate things called "domain", on two unrelated axes.**

| Namespace | Rows | Owner | What it partitions |
|---|---|---|---|
| `unified.domains` | 15 (`domain_abstract`, `domain_physical`, …) | `UniversalDomainMaster` + `domain_registry` | CATEGORY-level knowledge areas |
| `unified.concepts.domain` | ~30 (`security`, `code_generation`, `physics`, `kite17`, …) | concept ingestion | FIELD-level, where concepts actually live |
| `unified.learned_rules.domain_id` | 7 (`kite17`, `warehouse`, `syllogism`, `archive`, `identity_oracle`, …) | rule store | which WORLD a rule was induced in and may execute in |

Overlap between the registry (15) and the rule domains (7): **zero**. Overlap
between concepts and rule domains: partial — `kite17` (9 concepts) and `archive`
(4) appear in both; `warehouse`, `syllogism*` and `identity_oracle` do not.

**The domain system that was verified works, and is fully wired.**
`UniversalDomainMaster` is initialised in `core/main.py:849-862` and reached from
the coordinator, `neural_bridge`, `intrinsic_motivation` and
`hierarchical_abstraction`. `domain_registry` likewise. That is not in question.

**But it is on the concept axis, not the execution axis.** Every file in
`core/domain/` plus `universal_domain_master.py` — eleven files — contains
**zero** references to `learned_rules`, `rule_store`, `OperatorBinding`,
`binding_registry` or `grounded_operator`. The single exception is one line in
`evidence_producers.py`. `CrossDomainGrounder` reads
`unified.concept_relations` and `unified.concept_evidence`; it grounds
STRUCTURES between fields of knowledge. It transfers what is *known*. It has no
opinion on what can be *done*.

So on the execution path `domain_id` is a bare partition key with no authority
behind it, used in exactly two places:

    rule_store.load(domain_id=…)              which rules are in scope
    binding_registry.get(domain, predicate)   which tool acts for an operator

Nothing validates it against either domain authority, which is how `kite17` can
be a legitimate rule domain and simultaneously mean nothing to the registry.

### Defect 10b — nothing supplies `domain_id` to the planner either

`planning_engine.py:227` and `:258` both read `context.get("domain_id")`. Both
production callers of `plan_for_goal` — `autonomous_coordinator.py:8786` and
`:8893` — pass either no context at all or `{"system_state", "available_resources"}`.
**No caller anywhere sets `domain_id`.** So in production every task is built
with `domain_id=None`, and the executor's lookup becomes
`binding_registry.get("", predicate)` — the empty-string domain, which could
never match a registration even once one exists.

Two missing suppliers, in series, on the same chain. Fixing the binding registry
alone would not make it complete.

**What it needs:** something that registers an `OperatorBinding` per executable
predicate at startup, for the domains whose rules are validated. A binding is a
live tool handle, so the registry itself cannot be persisted — what must be
durable is the *registration*, performed on every boot from the rule store's own
list of validated actions. Not fixed.

---

## The reasoning folder — audit, 2026-08-24

22 files, ~20,000 lines. Audited by capability: every claim below was produced by
running the code, not by reading a header.

### What works, and it is the important part

**The substrate proves a syllogism with zero LLM calls.** Premises
`["All ravens are black", "Odin is a raven"]`, question `"Is Odin black?"`,
policy `STRICT_MODEL_FREE`:

    answer     Proved: odin_black
    confidence 0.98      verified=True      mode=SYMBOLIC
    steps      1. odin_raven -> odin_black  [Premise]
               2. odin_raven                [Premise]
               3. ~(odin_black)             [Negation of conclusion (for refutation)]
               4. odin_black                [Premises with the negated goal are unsatisfiable]
    telemetry  llm attempts 0   (1 embedding attempt: memory retrieval init)

That is a real refutation proof from a real deductive floor. The reasoning
capability is not in doubt.

### Defect 11 — the floor only opens when premises arrive separately

`DeterministicExtractor` reads the QUERY as a goal and the PREMISES from
`request.context`. Supply both and it formalizes. Put the same content in one
English string and all three deterministic formalizers decline:

| input | Passthrough | DeterministicExtractor | DerivedReading |
|---|---|---|---|
| `ravens(x) -> black(x)` | **OK** | no | no |
| `All ravens are black. Odin is a raven. Is Odin black?` | no | no | no |
| `A robin is a bird` | no | no | no |
| `2 + 2` | no | no | no |

`PassthroughFormalizer` accepts only text already in the formal grammar.
Nothing splits a compound English utterance into premises and a goal — so a
person typing the whole syllogism as one sentence gets the model, while the same
content arriving as `(context, query)` gets a proof. This is the same gap the
semantics work is aimed at, seen from the reasoning side.

### Defect 12 — `_model_available()` did not consult the model policy — FIXED 2026-08-24

`neural_bridge.py:2204` calls `model_can_serve(self.llm_service)`
(`:159-172`), which checks only whether a model OBJECT is loaded — `.model is
not None`, or `device == "remote"`. It never asks `core.model_policy`. The file
contains **zero** references to the policy module.

The consequence is in `_substrate_first`: when formalization fails it asks
`if self._model_available(): return None` and otherwise returns an honest
`REASON_UNSUPPORTED_INPUT` result. Under `STRICT_MODEL_FREE` a loaded model
still answers True, so the bridge routes to the model, the guard blocks the call
at the call site, and every mode returns:

    confidence=0.0   verified=False   reason=model_generation_failed

**The honest-reporting branch is unreachable whenever a model happens to be
loaded.** "The substrate cannot represent this input" and "the model call was
refused" are exactly the two things that code exists to keep apart, and it
reports the second for both.

**Fix.** `model_can_serve` now checks `get_model_policy()` first. The policy is
READ, not declared — `get_model_policy()` has no census side effect, unlike
`guard_model_use`/`model_use_permitted`. That distinction matters: asking
whether a model *could* serve is a routing question, and recording it as an
attempt would make a run that consulted no model report itself as
model-dependent.

Measured, same query, `STRICT_MODEL_FREE`, mode AUTO:

| | llm attempts | reason |
|---|---|---|
| before | 1 | `model_generation_failed` |
| after | **0** | **`unsupported_input`** |

`tests/test_reasoning_substrate.py` 63/63. One test there was already failing
before this change — `test_case_c_unsupported_input_reports_honest_inability`
asserted `model_required is True`, the model-first reading, while
`_substrate_first` sets it False and calls it a deprecated alias. The test now
asserts the substrate-first contract (`model_required is False`, plus
`teacher_available`/`teacher_consulted`).

### Defect 13 — three reasoning-mode vocabularies, mostly undispatched

| enum | file | members | dispatched |
|---|---|---|---|
| `ReasoningMode` | `reasoning_interfaces.py:33` | 3 (EPISTEMIC, ALEATORIC, BAYESIAN) | separate axis — uncertainty, not routing |
| `ReasoningMode` | `neural_bridge.py:34` | 7 (SYMBOLIC…AUTO) | **all 7 live**, `run_mode` at `:2009` |
| `ReasoningType` | `abstract_reasoning_engine.py:48` | 16 | **4** — DEDUCTIVE, INDUCTIVE, ABDUCTIVE, ANALOGICAL |
| `InferenceMethod` | `abstract_reasoning_engine.py:68` | 12 | **5** |

Two classes named `ReasoningMode` in one package is the shadow-enum pattern that
`tests/test_shadow_enum_guard.py` already polices for `ConceptType` and
`ReasoningStrategy`. `ReasoningMode` is not in that guard.

Declared and dispatched nowhere in the repo: `ReasoningType.TEMPORAL`,
`.SPATIAL`, `.COUNTERFACTUAL`, and all six `QUANTUM_*`;
`InferenceMethod.RESOLUTION`, `.CONSTRAINT_SATISFACTION`, `.FUZZY_LOGIC`,
`.NEURAL_REASONING`. `CAUSAL`, `LOGICAL` and `PROBABILISTIC` appear only inside
`unified_quantum_reasoning_system.py`.

### Defect 14 — quantum reasoning is initialised, counted, and never used

`unified_quantum_reasoning_system.py` is 805 lines. `core/main.py:1255-1268`
initialises it in Phase 9 unconditionally and increments
`stats['services_initialized']`. Every other reference in the repo is
construction, a `get_statistics()` call, or a presence check — **no call site
reasons with it.** Quantum hardware is gone; the system still reports a service.

### Defect 15 — two health checks that could not fail — FIXED 2026-08-24

`autonomous_coordinator.py:3163-3164`:

    "abstract_reasoning": {"initialized": hasattr(self.abstract_reasoning, 'initialized')},
    "quantum_reasoning":  {"initialized": hasattr(self.quantum_reasoning, 'initialized')},

`hasattr` is True whenever the attribute EXISTS. A subsystem whose
`initialized` flag is `False` reports `initialized: True`. Same fabricated-signal
shape as the five health checks already corrected.

**Fix.** `_subsystem_readiness()` in the same file reports two independent
facts, because collapsing them loses the one that matters:

    attached=False, initialized=False   never constructed
    attached=True,  initialized=False   constructed, initialise failed  <- THE FAILURE CASE
    attached=True,  initialized=True    ready
    attached=True,  initialized=None    publishes no flag -- "does not say", not "says no"

Verified: on a subsystem with `initialized = False`, `hasattr` returned `True`
and the replacement returns `False`.

### Defect 16 — two orphaned modules

| file | lines | references anywhere |
|---|---|---|
| `analogy_diagnostics.py` | 319 | **zero** — not core, not tests, not experiments |
| `context_config.py` | 127 | its own test only; `ContextConfig`/`DEFAULT_CONFIG` have no production reader |

`context_manager.py` and `context_compression.py` do not import it — they carry
their own window/compression settings, so the config authority is duplicated
and the declared one is the dead copy.

### Defect 17 — debug `print()` on production paths — FIXED 2026-08-24

`print()` writes to stdout, cannot be silenced by log level, and is not
capturable by the logging pipeline. Counts before any `__main__` block:

| file | prints | note |
|---|---|---|
| `core/agents/memory_agent.py` | **46** | no `__main__` at all — every one is production. `store_memory` prints 7 lines per call |
| `core/reasoning/neural_bridge.py` | 18 | `:2800+` dumps the **full model prompt** to stdout — that prompt carries injected memory |
| `core/reasoning/analogy_discovery.py` | 14 | |
| `core/tools/ai_ml_tools.py` | 16 | |

The memory authority and the reasoning entry point are the two worst offenders.
The bridge's prompt dump is also a disclosure concern: injected memories go to
stdout in plain text.

**Correction to the table above.** Those counts were "prints before the
`__main__` guard", which over-counts: a module's `async def main()` demo sits
BEFORE its guard line. Re-measured with an AST walk that excludes demo
functions, `__main__` blocks and docstrings, the real production figures were
`memory_agent.py` 46, `ai_ml_tools.py` 10, `neural_bridge.py` 18 —
and `analogy_discovery.py` **0**, all 14 of its prints being inside its `main()`
demo.

**Fix.**

- `memory_agent.py` — all 46 converted: 39 to `logger.debug`, 7 to
  `logger.error`. Four were then reclassified down, because they described
  normal operation rather than failure: a worthiness-filter DECLINE is the
  filter working, and a skipped duplicate check is degraded-but-fine. An error
  log that fills with correct decisions is not an error log.
- `neural_bridge.py` — the prompt dump now renders through
  `logger.debug`, guarded by `logger.isEnabledFor(DEBUG)` so the string is not
  even built when it is off. Kept, because seeing the final prompt matters when
  a model answers oddly; moved, because stdout cannot be silenced or filtered
  and the prompt carries injected memories in plain text.
- `ai_ml_tools.py` — 10 converted.

Verified by an AST sweep of all of `core/`: **two files still call `print()`
outside a demo, and both are correct** — `migrate_to_capabilities.py`, a
developer helper whose output IS its prints, and `command_console.py`, which
writes coloured output to `sys.stderr` because it is a console.

Verified live through the real entry point: `store_memory` wrote **0 bytes to
stdout**, every step visible at DEBUG, and the filter declined the test note as
`trivial_factual_lookup` — the correct answer for a throwaway, not a break.
38 memory tests pass.

---

### Defect 18 — checkpoints are written, pruned, and never read

**The substrate does not have checkpoints.** What `checkpoint_manager.py` stores
is executor-loop state, and the store is write-only.

The machinery itself is sound — round-trip verified exact, gzip, pruning, stats.
And it is genuinely live: `convergence_gate.check_convergence` calls
`checkpoint_state` (`:835`), reached from the executor at
`general_purpose_executor.py:2193` and `:3048`. `data/convergence_checkpoints/`
holds **100 files, 1.5 MB, written 14–20 Aug — exactly at the
`max_checkpoints=100` cap**, so it is continuously pruning.

But nothing reads any of it back. `load_checkpoint`, `get_latest_checkpoint`
and `restore_from_latest` have **zero callers outside the module**. The gate
computes its own state delta from `self._task_states`, an in-memory list, never
from the files. So every checkpoint is written, held until the cap pushes it
out, and deleted having never been read once.

Two further points:

- What is saved is `{tool_results, epistemic_mutations}` — iteration state of
  the execution loop. It is not substrate state: no rules, no concepts, no
  bindings, no reasoning record. Restoring one would not restore Torin to
  anything.
- `checkpoint_manager`'s DEFAULT directory `data/checkpoints/` is empty and
  always has been; the only real user overrides it. The health entry
  (`health_monitor.py:1546`) calls `get_checkpoint_manager()`, the singleton on
  the DEFAULT path — so health reports on a manager that is not the one doing
  the work.

**Decision needed:** either give restore a real consumer (crash recovery for
interrupted tasks) or retire the write. Writing 1.5 MB nothing reads is the
cost; the false impression that state is recoverable is the risk.

### Defect 19 — cached checkpoint loads were invisible — FIXED 2026-08-24

`load_checkpoint`'s cache-hit early return skipped `stats['total_loaded'] += 1`.
Since `save_checkpoint` populates the cache, the ordinary save-then-restore
sequence reported `total_loaded=0` forever — and `health_monitor.py:1546` reads
that number, so "restore has never been exercised" and "restore works and is
warm" were the same reading. Now counted; verified 0 → 2 for two real loads.

---

## Substrate capability vs model scaffolding — the reasoning folder

The question this answers: which of these 21 files exist because Torin reasons,
and which exist because a language model needed help iterating? Measured, not
inferred — LLM call sites counted per file, and the two execution paths compared
structurally.

### Why the substrate needs no convergence gate and no checkpoints

The convergence gate and the checkpoint store were built so a model could run a
long tool-use loop without running forever. That need does not transfer.

    MODEL PATH      general_purpose_executor.py:2156
                    `for iteration in range(max_iterations)` over a CONVERSATION.
                    Nothing proves it finishes, or that it is making progress, so
                    a gate watches the state and declares a fixpoint when it
                    stops changing. The state it watches includes
                    `conversation_history`.

    SUBSTRATE PATH  _try_substrate_execution
                    Executes ONE proved operator. Its four loops iterate over
                    `rule.action.args`, `rule.preconditions`, `match_literal`
                    candidates and `evidence.verifications` -- every one bounded
                    by the rule itself. There is no "until it stops changing".

**Termination is proved at planning time, not detected at runtime.** A state plan
is a finite ordered chain of operators, each with verified preconditions and
verified effects. Convergence is a property the search establishes before
anything executes. There is no fixpoint to watch for, so there is nothing for a
gate to watch, and nothing whose intermediate state is worth checkpointing.

The same argument disposes of the context machinery: a model has a finite context
window that fills as a conversation grows, so turns must be counted, budgeted and
compressed. The substrate's context is the rule store and the observed world --
both QUERIED at the moment of use, never accumulated into a prompt. Nothing
fills up.

### The four groups

**GROUP 1 — model-loop scaffolding. No substrate equivalent is needed.**

| file | lines | what it is |
|---|---|---|
| `context_compression.py` | 517 | compresses conversation history; calls a lightweight LLM to do it |
| `checkpoint_manager.py` | 462 | write-only store of executor-loop iteration state (defect 18) |
| `context_manager.py` | 447 | conversation token budgets, turn counts, compression triggers |
| `context_config.py` | 127 | config for the above; orphaned, no production reader (defect 16) |
| *(`core/execution/convergence_gate.py`)* | — | the fixpoint detector these serve |

~1,550 lines. Every one is about making a conversation with a token limit
survive a long loop. None of it is reachable from, or useful to, the substrate
execution path.

**CORRECTION — THE EXECUTOR IS NOT THE MODEL PATH.** An earlier draft of this
section said these retire "when the model-backed executor does". That was wrong
and worth stating plainly, because the mistake matters architecturally.

`general_purpose_executor` IS the execution authority. Nothing goes around it.
`execute_task` opens with `_try_substrate_execution`, which lives in that same
file — the substrate path is the executor's FIRST branch, not an alternative to
it. And it executes real tools through the same door everything else does:

    result = await get_tool_registry().execute_tool(
        binding.tool_name, binding.parameters(action.args))
    # "Safety and governance are enforced inside execute_tool,
    #  which is the single evaluation point for every tool call."

It then reads the world back with `binding.observe()` — independently of what
the tool claimed — verifies the rule's effects against what actually changed,
attributes the outcome, and writes runtime evidence back to the rule store. Tool
execution, safety, and learning are one path.

So what Group 1 serves is the ITERATION LOOP inside the executor, not the
executor. Retiring it means retiring `for iteration in range(max_iterations)`
once the substrate path can supply operators for the work. The executor stays.
`execute_tool` stays. The tools stay.

**GROUP 2 — model-free already. 0 LLM call sites.**

`advanced_proof_engine` (654, Z3) · `constraint_solver` (269, Z3) ·
`temporal_reasoning` (1375, the state planner) · `bayesian_uncertainty` (1528) ·
`hypothesis_testing` (1424) · `hierarchical_abstraction` (2331) ·
`analogy_discovery` (1086) · `formal_argumentation` (1047) ·
`epistemic_engine` (875) · `reasoning_interfaces` (280) · `unification` (172) ·
`arithmetic_reading` (126) · `value_authority` (103)

**This is measured model-independence and reachability, NOT a capability
verdict.** Each still has to be exercised the way the syllogism was — real
input, real output, checked. `formal_argumentation` (2 production references)
and `hierarchical_abstraction` (3) are the least-attested and should be tested
first.

**GROUP 3 — mixed, and now substrate-first in both.**

`neural_bridge` (3802) is the router; AUTO probes deterministic formalizers
before any model, verified 0 LLM attempts (defect 12).

`abstract_reasoning_engine` (2117) — its control flow was ALREADY correct:
`DeductiveReasoningStrategy.reason` applies rules first and always, and consults
the model only to extend the result. What was wrong was what came back (defect
20 below).

**GROUP 4 — dead.**

`unified_quantum_reasoning_system` (805) — initialised, counted as a service,
never reasoned with (defect 14). `analogy_diagnostics` (319) — zero references
anywhere (defect 16).

### Defect 20 — the model graded its own conclusions into memory — FIXED 2026-08-24

`abstract_reasoning_engine` asked the model to `Indicate confidence (0.0-1.0)`,
read that number back with a regex, and assigned it to **four** fields:

    confidence=confidence, logical_validity=confidence,
    evidence_strength=confidence, coherence_score=confidence

So `_rank_conclusions`' weighted composite — `0.4*conf + 0.3*validity +
0.2*evidence + 0.1*coherence` — resolved to exactly the model's self-grade, and
`_validate_conclusion` and `_filter_conclusions` had nothing independent to check
it against. Four "quality metrics", one source, and that source was the thing
being measured.

Three more faults in the same path:

- **A missing `CONFIDENCE:` line defaulted to 0.7** — silence indistinguishable
  from a stated 0.7. The absence-read-as-value shape again.
- **An unparseable reply became a conclusion anyway**, taking the first line of
  the response with a hardcoded 0.75.
- **`supporting_premises=[p.premise_id for p in context.premises]`** — every
  conclusion claimed every premise as support, whatever it said.

**Why it mattered beyond this file.** `overall_confidence` is the mean of all
conclusion confidences, and `_store_in_memory` drives `is_novel` (>0.8),
`consequence_level` HIGH (>0.85), `actionable` (>0.7), `created_new_knowledge`
(>0.75), `impact_assessment` "critical" (>0.9), `requires_human_review` (<0.6)
and the stored memory's own `importance_score` from it. A model writing
`CONFIDENCE: 0.95` about its own guess got that guess stored as high-confidence,
novel, actionable, critical-impact new knowledge — and explicitly NOT flagged for
review. A direct contamination path from model self-assessment into the memory
store.

**Fix.** `ReasoningConclusion` gained `origin` — `derived` or `proposed`. Model
proposals carry confidence 0.0, no quality scores and no claimed premises; the
prompts no longer ask for a self-rating; the two fabricating fallbacks are gone.
Quality metrics are computed over derived conclusions only. Derived outranks
proposed as the PRIMARY sort key, not by arithmetic accident. `origin` travels
into memory with the conclusion, so recall cannot hand a suggestion back as
something Torin concluded.

Proposals are RETAINED, not filtered out — a model may propose. Applying the
derived thresholds to a proposal would have deleted the model path silently
rather than demoting it, and that would look identical to the model producing
nothing.

Measured after the fix:

| case | before | after |
|---|---|---|
| model self-grades 0.95 | conf 0.95, all 4 metrics 0.95, all premises cited | `origin=proposed`, conf 0.0, no premises |
| model states no grade | conf 0.7 | identical to above — silence is not a score |
| unparseable reply | 1 conclusion @ 0.75 | **0 conclusions** |
| 1 derived @0.9 + 1 proposal | overall 0.925 | **0.900** |
| proposals only | overall 0.95 → stored as novel/actionable/critical | **0.000** |
| ranking | by composite | derived before proposed, always |

124 reasoning tests pass.

---

### Defect 10c — tools are never projected as operators in production

The third missing supplier in the execution chain, found while tracing what a
binding would bind TO.

`tool_registry.project_capabilities()` exists and is complete. Its docstring
states the purpose exactly: *"The concept graph knew about operators Torin had
LEARNED and nothing about the ones it could already perform, so cross-domain
grounding could recognise an unfamiliar situation as a learned rule but never as
something there was already a tool for."* It enumerates eager AND lazy tools,
calls `submit_tool_capability` on each, and counts projected / no-structure /
failed separately.

**Its only caller is `experiments/verify_wiring.py:126`.** Zero production
callers.

**But the data IS there, and this is weaker than it first looked.** An earlier
reading of this recorded "0 concepts in the `tools` domain" and called the
projection a false success — both wrong, and worth correcting because the
correction is the interesting part.

The domain a projected tool is filed under is
`getattr(tool.category, "value", domain)` — the tool's own CATEGORY, not the
literal `"tools"`. So they are filed as `security`, `code_generation`, `system`,
`testing` and so on, which is exactly the `unified.concepts.domain` distribution
recorded above. Measured:

    concept_evidence rows from tool declarations   2,299
    distinct concepts they support                   990   (of 1,182 total)

**Roughly 84% of the concept store is projected tools.** Re-running
`project_capabilities()` now reports `{tools: 372, projected: 372, failed: 0}`
and writes nothing new — per-tool it returns `candidates=11, created=0,
reinforced=11`. That is idempotent reinforcement working correctly, not a
silent failure.

One genuine caveat on the counter: `project_capabilities` counts a tool as
`projected` when `result.read_successfully` is true, and that property means
"no extractor raised" — not "a concept was stored". A tool read cleanly that
yielded nothing would still count as projected. It has not misreported yet
because nothing currently yields nothing, but the counter is measuring the
wrong thing.

So the real gap is a REFRESH gap: the projection ran at some point and nothing
re-runs it, so a tool added, removed or re-declared after that point never
reaches the concept graph.

So the three suppliers this chain needs, in order:

| # | supplier | state |
|---|---|---|
| 10b | `context["domain_id"]` reaching the planner | no caller sets it; every task gets `domain_id=None` |
| 10c | tools projected as operators | data present (990 concepts); nothing re-runs it |
| 10 | operator predicate → `OperatorBinding` registrar | **does not exist** |

10c is a startup call site (a refresh, since the data exists). 10b is a call site. 10 is the real design question: what
decides which tool performs `MOVE(?X0, ?X2, ?X1)`? The code answers it in the
projection docstring — cross-domain grounding is meant to recognise that a
learned operator and a declared tool are the same structure. That is why tools
were given concept representations at all. The registrar that turns such a
correspondence into a binding was never written.

---

### Defect 21 — memory was NOT stored the same for each reasoning mode — FIXED 2026-08-24

Two separate mode biases, both measured by running the bridge.

**(a) The substrate's own answers were never remembered.**

`reason()` had two exits. The substrate-first early return sat ~90 lines above
`_update_stats` and the memory capture, so neither was reachable from it. Proof,
measured with a spy on `_capture_reasoning_memory`:

| mode | answer | confidence | captured |
|---|---|---|---|
| AUTO | `Proved: odin_black` | 0.98 | **0** |
| SYMBOLIC | `Proved: odin_black` | 0.98 | 1 |
| HYBRID | `Odin is black.` | 0.599 | 1 |

The IDENTICAL result — same answer, same confidence, the same Z3 refutation
proof — was recorded when reached through SYMBOLIC and dropped when reached
through AUTO. Only the door differed.

AUTO is the default and the substrate-first mode. So everything Torin proved for
itself through the normal path was forgotten, while everything a model produced
was remembered. Survivorship bias aimed squarely at the substrate: anything
learning from that record would conclude the model was the more productive
reasoner. It also meant substrate answers never reached `_update_stats`, so they
were invisible to the bridge's own statistics.

**Fix.** One exit: `_finish(request, result)` does stats + capture, and both
paths return through it. The two capture conditions are unchanged and both still
matter — an empty answer is a refusal and must not be stored as a semantic
memory, and inside the executor's agent loop the conversation is captured once
at task end rather than per iteration. After the fix AUTO captures 1; SYMBOLIC
on an unformalizable input still captures 0, which is correct.

**(b) One mode was scored as more worth remembering than the others.**

`_calculate_complexity_score` awarded a flat `+0.2` for
`mode_used == ReasoningMode.HYBRID`. Complexity feeds `importance` at 0.4x, so
every hybrid answer was 0.08 more important than an identical answer from any
other mode. Measured on identical content and identical steps:

| mode | confidence | importance (before) | (after) |
|---|---|---|---|
| symbolic | 0.98 | 0.838 | 0.838 |
| hybrid | 0.98 | **0.918** | 0.838 |
| symbolic | 0.35 | 0.750 | 0.750 |
| hybrid | 0.35 | **0.830** | 0.750 |

A hybrid guess at 35% confidence was stored as almost exactly as important
(0.830) as a Z3-verified proof at 98% (0.838). Nothing in the content justified
it; the mode alone did. Removed — complexity is a property of the result, not of
which engine produced it.

**Still there, and left alone deliberately:** Factor 4 scores lower confidence as
higher complexity. That is defensible as a complexity heuristic (harder problems
are less certain), and its net effect on importance is still positive in
confidence — `d(importance)/d(confidence)` works out to about +0.12 while the
term is uncapped. Noted rather than changed.

101 memory and reasoning tests pass.

**Verified against the real system, after the first verification was found
inadequate.** The fix was originally checked with a spy that replaced
`_capture_reasoning_memory` and returned without writing — which proves the CALL
happens and says nothing about whether a ROW appears. That is the same
"can a return value fake success?" question this audit asks of everything else,
and it had not been asked of the check itself.

Re-run with no spy, no stub — the real bridge, the real memory agent, the real
filter, the live Postgres, success defined as a row:

    answer      Proved: zq34597891e5_black
    confidence  0.98    verified=True    llm calls 0
    filter      should_store=True -> ACCEPTED
    result      rows in memory_hot.memory_hot: 1

(The table is `memory_hot.memory_hot` — schema and table share the name. It is
not in `unified`.)

### Defect 22 — a refused embedding lost the memory — FIXED 2026-08-25

Found by that same real run. With the policy set strict, the whole chain
succeeded up to the last step and then failed:

    Write queue worker: store_memory failed: embedding inference at
    embedding_service.generate_embedding is forbidden under strict_model_free

Captured, queued, worker ran, filter ACCEPTED, memory id minted — then storage
required an embedding, the guard refused it, and the store failed outright. No
degraded path, no storage without a vector.

So reasoning is model-free and memory is not. A fully model-free run can prove
things and cannot keep them, which means an experiment run under
STRICT_MODEL_FREE silently accumulates no episodic record — and any claim about
what the substrate "remembered" during such a run is a claim about an empty
store.

**THIS WAS WRITTEN UP AS A CHOICE, AND THAT WAS WRONG.** The entry above offered
"either storage tolerates a missing embedding, or STRICT_MODEL_FREE is
documented as reason-only". The second is not an option. Memory not depending on
a model is the point of the memory system; a model-free run that silently
accumulates no record cannot support any claim about what was remembered. It was
a bug, not a trade-off.

**And the code already intended to support it.** The store reads:

    embedding = self.embedding_service.generate_embedding(content) \
        if self.embedding_service else None

An ABSENT service already yields `None` and the memory is stored unvectorised.
What was unhandled was a service PRESENT and REFUSING: `generate_embedding`
calls `guard_model_use`, which raises `ModelUseForbidden` under
STRICT_MODEL_FREE, and that propagated out of `store_memory` and lost the record
entirely.

So a refusal behaved worse than an absence — the inverse of the
absence-read-as-value defect that runs through this document.

**Fix:** a refused embedding yields the same `None` an absent one does. The
vector is a RETRIEVAL AID, not the memory: without it the record is still
stored, still readable, still exact-matchable, and only semantic search over it
waits for a backfill. Losing the record instead of the aid is strictly worse.

Verified with the model fully blocked:

    stored=True    ROWS IN THE STORE: 1
    llm=0          embedding attempts=3   blocked=3
    vector=False   findable by content: 1

101 memory tests pass.

---

### Defect 23 — the eleven thinking modes had no single vocabulary and no router — PARTLY FIXED

`ReasoningType` named eleven classical kinds of thinking. Four had strategies.
Nothing selected any of them by that enum.

**What was actually deciding.** Three unconnected things, none of them the enum:

| where | how | produced |
|---|---|---|
| `ReasoningType` | — | the declared vocabulary, consulted by nothing that routes |
| `NeuralBridgeRouter._build_context` | 6 keyword lists | a routing MODE |
| `_hybrid_reasoning` | 3 keyword lists | which ENGINES to load |

The third was already doing thinking-mode selection without saying so:
`is_temporal` IS `ReasoningType.TEMPORAL`, `needs_proof` IS
`ReasoningType.LOGICAL`. Because they never named the enum, a member could be
added that nothing would ever select and nobody would notice — which is what
happened to CAUSAL, COUNTERFACTUAL, SPATIAL and FUZZY.

**Fixed so far.**

1. **One vocabulary.** `ReasoningType` had THREE declarations
   (`reasoning_interfaces`, `abstract_reasoning_engine`,
   `unified_quantum_reasoning_system`); `A.DEDUCTIVE == B.DEDUCTIVE` was False
   while both printed `'deductive'`. Merged to 18 members — the 11 classical
   plus 7 quantum — with `CLASSICAL_REASONING_TYPES` naming the list a router
   must reach. `InferenceStrategy` (5) and `InferenceMethod` (12) merged to 15,
   the latter now an alias. `ReasoningMode` meant three unrelated things: the
   interfaces one is renamed `UncertaintyMode` (it described where uncertainty
   comes from, never a way of thinking), `enhanced_logical_agent.ReasoningMode`
   was a fourth `ReasoningType` under the wrong name and is now an alias, and
   the quantum one is `QuantumTaskType` because what it selects is a quantum
   ROUTINE. All three removed from `KNOWN_SHADOW_DEBT` and added to the guard.

2. **One classifier.** `REASONING_TYPE_MARKERS` + `kinds_of_thinking_for()` in
   `reasoning_interfaces`, covering all 11 and returning EMPTY when nothing
   matches — a default of "deductive" would make an unclassifiable request
   indistinguishable from a genuinely deductive one. `_hybrid_reasoning`'s three
   private booleans now read from it.

3. **CAUSAL and COUNTERFACTUAL registered**, delegating to `temporal_reasoning`
   — whose `establish_causal_link`, `trace_causal_chain`, `predict_effect`,
   `project_future_state` and `compare_future_states` had **zero callers in the
   entire repository**. No algorithm was written; the reasoning stayed where it
   already lived.

**Three bugs in that new code, found by testing it and fixed:**

- **Proposition identity.** `create_proposition` mints a fresh id per call, so
  "write failure" got one id as the effect of premise 1 and another as the cause
  of premise 2. The links shared no node, and a real two-step chain reported the
  INTERMEDIATE step as the root cause — a confident, plausible, wrong answer.
  Composing chains the premises never state individually is the whole reason to
  consult a causal engine, and it was exactly what silently did not happen.
- **A reachability gate that could not fail.** The counterfactual state was
  projected with `required_actions=[alternative]`, and reachability is decided
  by whether a missing condition appears in some required action — so every
  alternative was achievable by construction and reachable/unreachable cases
  produced identical output. Now the actions are the context's own rules.
- **Confidence keyed by node instead of edge.** A node inherited the weakest
  link touching it anywhere, so a conclusion resting entirely on a 0.90 link was
  scored 0.60 by a link it does not use.

Measured after the fixes, model blocked, 0 LLM calls:

    root cause of write failure     -> disk exhaustion   0.90  (2 steps)
    root cause of checkout timeout  -> disk exhaustion   0.60  (3 steps, weakest edge)
    counterfactual, action available    -> 0.70 "would not have been preferable"
    counterfactual, nothing can do it   -> 0.40 "could not have obtained"
    no causal claim present             -> 0 conclusions, overall 0.0

**Still open:** SPATIAL and FUZZY have no engine and must be built. The router
(`_build_context`'s six flags) still selects a routing mode rather than a kind
of thinking, so the 11 are reachable through the abstract engine but not yet
requestable through the bridge. 120 tests pass.

### Defect 24 — `LLMFormalizer` named the substrate after a model — FIXED 2026-08-24

Renamed `ProposedReadingFormalizer`, source `"llm"` -> `"proposed"`. The
substrate DERIVES readings — `PassthroughFormalizer` (already formal),
`DeterministicExtractor` (shapes it knows), `DerivedReadingFormalizer` (a
procedure it learned). This is the other case: it could not read the input, so a
reading is PROPOSED from outside and re-parsed and grounded before acceptance.
Named for what it produces from the substrate's side, not for what supplies it —
and deliberately not "teacher", which is `core/learning/`'s vocabulary
(`teacher_policy`, `llm_teacher`), not the substrate's.

Kept, not deleted: measured reachable once each from AUTO and from SYMBOLIC, so
the substrate does use it as coverage when its own readers decline. Its output
carries `requires_model=True`, which makes `premises_trusted` False and records
`substrate_formalized=False`.

**Bug fixed in it:** the return read
`statements=locals().get("every_statement") or [statement]` and no such variable
exists in that method — always None, always the fallback, reading as though a
multi-claim reading were being assembled. Copy-pasted from
`DeterministicExtractor.formalize`, where the variable IS conditionally defined
and the pattern is legitimate; that one was left alone.

---

### Defect 25 — `AbstractReasoningEngine.reason()` never returned — FIXED 2026-08-24

Found while testing the new strategies. **Every** call to
`AbstractReasoningEngine.reason()` blocks indefinitely. Located precisely by
asyncio task introspection rather than guessed:

    suspended frames of the reasoning task:
      core/reasoning/abstract_reasoning_engine.py:1950 in reason

Line 1950 is `await self._update_learning(result)`, which calls
`UnifiedLearningSystem.learn_from_experience`.

**It is not caused by the new strategies.** It reproduces with an EMPTY result
and no strategy involved at all, and with `learning_engine` reached directly. It
is also independent of the model policy — it blocks identically under NORMAL and
STRICT_MODEL_FREE, and at a 90-second wait, so it is not the 30 s Slack timeout
on that path either.

**What the log shows before it blocks.** The inner work completes and reports
its own failure:

    Learning from example (type: supervised)
    Meta-learning selected strategy: transfer (trials=533, success_rate=98.9%)
    Memory ACCEPTED by filter: rule=behavioral_consequence
    Learning from example failed: <embedding blocked, under STRICT only>
    Applied temporal decay to hot tier memories

So `learn_from_example` logs completion and the caller still never resumes.
The suspension is after that point.

**Why it matters beyond this file.** `reason()` is the only entry to the
strategy registry, so every one of the eight registered kinds of thinking is
unreachable through the engine in-process. They are individually correct —
verified by calling the strategies directly — but nothing can currently call
them through their own engine.

**THE CAUSE: a Slack notification.** Found by instrumenting every awaited call
on the path rather than by reading:

    ENTER learn_from_experience
    ENTER learn_from_example
    ENTER select_strategy   EXIT 4ms
    ENTER store_memory      EXIT 148ms
    ENTER slack             (never exits)

`_send_slack_notification` retries on 429 and 5xx by sleeping and calling itself
again, up to `max_retries`, and each attempt carries its own 30 s
`ClientTimeout`. Those bound one ATTEMPT, never the sequence, so the total wait
is retries x (timeout + backoff) and is unbounded from the caller's side. It
still had not returned at 90 s.

So: **every kind of thinking was unreachable through its own engine because a
chat message would not resolve.** Reasoning -> learning -> notification, and the
notification was on the critical path.

`_update_learning` is wrapped in `try/except Exception`, which catches errors and
does nothing for a hang — the failure mode it was not written for. That is why
it presented as a silent stall rather than an error.

**Fixed in two places, because one alone is not enough.**

1. `SlackNotifier.SEND_DEADLINE_SECONDS = 35.0` bounds one `send_notification`
   call INCLUDING every retry and backoff. On expiry the notification is dropped
   and `False` is returned — a lost message is a far smaller failure than a
   stalled substrate, and the return value keeps the two distinguishable. This
   protects every caller, not just this path.

2. `UnifiedLearningSystem._notify()` sends WITHOUT awaiting, replacing
   `await self.slack_notifier.send_notification(...)` at seven sites. A bound is
   not the same as not waiting: reasoning should not pay 35 s either, and it has
   no reason to wait even 35 ms for a chat message. Tasks are held in a set
   because asyncio keeps only a weak reference and an unreferenced task can be
   collected mid-flight — silently, and only sometimes.

Measured after the fix, through the real engine:

    CAUSAL   OK  0.3s  conclusions=2
    SPATIAL  OK  0.0s  conclusions=1
    FUZZY    OK  0.0s  conclusions=1

125 reasoning and memory tests pass.

**The strategies themselves are verified**, called directly, model blocked,
0 LLM calls:

    spatial   chip inside socket, socket inside board -> chip inside board 0.60
              (weakest step; converses derived too)
    spatial   fan near chip, chip near port          -> NOTHING derived
              (adjacency is not transitive; inventing "fan near port" is
               exactly the plausible-but-wrong output this avoids)
    fuzzy     "mostly full" -> degree 0.80, "slightly backed up" -> 0.25
              conjunction under the Zadeh min-rule -> 0.25
    causal    two-step chain -> correct root cause at the weakest edge

**Converse inaccuracy in SpatialReasoningStrategy — FIXED.** Converses of STATED
relations ("socket contains chip" from "chip is inside the socket") were reported
as derived. They are restatements, and counting them inflated the result: two
premises produced four "conclusions", half of them the premises restated. `known`
now includes the converse and symmetric form of every stated relation, so the
same case yields the two genuine derivations (`chip inside board`,
`board contains chip`) and nothing else.

---

### All eleven thinking modes registered and model-free — 2026-08-24

`_initialize_strategies` registered four and ended with "Additional strategies
would be added here". It now registers **11 of 11**, and none of them calls a
model.

| mode | how it works | ms | LLM |
|---|---|---|---|
| DEDUCTIVE | rule application by unification | 65 | 0 |
| INDUCTIVE | grouping -> pattern -> generalisation | 3.9 | 0 |
| ABDUCTIVE | backward rule search, Occam, ceiling 0.7 | 3.0 | 0 |
| ANALOGICAL | structure mapping | 3.1 | 0 |
| CAUSAL | `temporal_reasoning` causal links + chains | 7.1 | 0 |
| COUNTERFACTUAL | `project_future_state` + `compare_future_states` | 6.1 | 0 |
| SPATIAL | **implemented here** — transitive closure over stated relations | 3.3 | 0 |
| FUZZY | **implemented here** — Zadeh operators + hedges | 3.2 | 0 |
| LOGICAL | `advanced_proof_engine` (Z3) | 31.1 | 0 |
| PROBABILISTIC | `bayesian_uncertainty` prior -> posterior | 3.2 | 0 |
| TEMPORAL | `temporal_reasoning.evaluate_temporal_formula` | 4.6 | 0 |

Five of these adapt engines that already existed and could not be reached by
name. `evaluate_temporal_formula`, `establish_causal_link`, `trace_causal_chain`,
`predict_effect`, `project_future_state` and `compare_future_states` had **zero
callers anywhere in the repository** before this.

### Defect 26 — DEDUCTIVE and INDUCTIVE consulted the model unconditionally — FIXED

Both ran their rule/pattern path and then called the model regardless of the
result. The only thing that skipped it was the absence of a service object:

    if not self.llm_service:
        return conclusions
    model_conclusions = await self._vlm_powered_deduction(context)

The docstring called it "consulted afterwards to extend the result". That cannot
be right for these two. **Deduction is the relation of following from the
premises**; a statement the rules cannot derive is not a deduction but a guess
wearing the label. **Induction is generalisation supported by the examples
given**; a pattern they do not support is not an induction from them. There is
no coverage gap for a model to fill, because the gap IS the answer.

It had also stopped contributing anything: after defect 20 gave model proposals
`origin="proposed"`, confidence 0.0 and no cited premises, they were excluded
from `overall_confidence`, ranked below every derived conclusion, and counted in
no quality metric. What remained was an unscored sentence.

**And it masked failure.** DEDUCTIVE returned a conclusion at confidence 0.00 —
the rule path had contributed nothing and the model was covering for it. Before
defect 20 the model's self-graded number would have filled that gap and the
result would have read as successful deduction.

| | before | after |
|---|---|---|
| DEDUCTIVE | 33,650 ms, 1 LLM call | **65 ms, 0** |
| INDUCTIVE | did not finish in 60 s | **3.9 ms, 0** |

The reasoning paths are UNCHANGED — rule application, and
grouping/pattern/generalisation, both intact. Only the model call was removed.
The four now-unreachable methods (`_vlm_powered_deduction`,
`_parse_vlm_response`, `_vlm_powered_induction`, `_parse_inductive_response`,
268 lines) are in `backups/vlm_strategy_methods_retired_20260824/`.

**Both verified working after removal**, with the formal notation the substrate
actually reads:

    human(?X) -> mortal(?X)  +  human(socrates)   -> mortal(socrates)  0.80
    ... with human(plato) too                     -> both conclusions
    rained -> lawn_wet       +  lawn_wet          -> rained    (abduction)

**Two notation limits found, not defects in the strategies:**

- Variables need the `?` prefix (`VARIABLE_PREFIX = "?"`), so `human(X)` reads
  `X` as a constant and matches nothing. Silent — it produces no conclusions
  rather than reporting an unreadable rule.
- `_as_atom` requires parentheses, so propositional atoms like `socrates_human`
  are unreadable to this strategy.
- A conjunctive rule `raven(?X) & bird(?X) -> black(?X)` produced nothing; `&`
  in the body may not be split. NOT investigated.

Each is defect 11 surfacing again from a different side: the substrate reasons
well over its own notation and cannot read the same content stated in English.

131 tests pass.

---

### Defect 27 — the router could reach only 3 of the 11 kinds — FIXED 2026-08-24

Registering eleven strategies does not make them reachable. Tested, and they
were not.

**`neural_bridge._abstract_reasoning` is the only production code that builds a
`ReasoningContext`,** and it hardcoded the allowed kinds:

    allowed_reasoning_types=[
        ReasoningType.DEDUCTIVE,
        ReasoningType.INDUCTIVE,
        ReasoningType.ANALOGICAL,
    ],

`_select_strategies` filters on exactly that list, so CAUSAL, COUNTERFACTUAL,
SPATIAL, FUZZY, LOGICAL, PROBABILISTIC, TEMPORAL and ABDUCTIVE could not be
selected whatever the query asked. Eight kinds registered, implemented, tested —
and unreachable.

It also passed `facts=[request.query]` and **no premises at all**, so
`DeductiveReasoningStrategy.is_applicable` (`len(context.premises) > 0`) could
never pass through that path either.

**Second defect, found by the same test: two rules for what "applicable" means.**
The three original strategies re-checked `ReasoningType.X in
context.allowed_reasoning_types` inside their own `is_applicable`. That was
redundant on the normal path — `_select_strategies` had already filtered — and
wrong on the other one: when a caller declares no allowed types,
`_select_strategies` falls back to "every applicable strategy", and an `in []`
test is False. So the three original strategies could never fire on the fallback
path while the eight added later, which test only for material, could.

**Fix.** The bridge now populates `allowed_reasoning_types` from
`kinds_of_thinking_for(request.query)`, falling back to every classical kind
when the query carries no marker — each strategy's `is_applicable` then refuses
unless the material is present, which is a better filter than any list fixed in
advance. Request context is passed as PREMISES, not only as facts. The redundant
allowed-type checks are gone from the three original strategies; the single
remaining one is in `_select_strategies`, which is the right owner.

**Verified end to end** — query classified, strategy selected, conclusion
produced, model blocked from contributing:

    routed to the expected strategy : 11/11
    produced conclusions            : 11/11
    llm calls                       : 0 on every case

The earlier layer-2 result of 3/11 was a bad test, not a bad router: it supplied
a question with no premises, rules or targets, so `is_applicable` correctly
refused for eight of them. Refusing when the material is absent is the behaviour,
not a failure — but it does mean a routing test has to carry the material, or it
measures nothing.

**A second bad test, and the more important one.** The 11/11 result above was
produced by calling `kinds_of_thinking_for` BY HAND and passing the result into a
hand-built `ReasoningContext`. That exercises the classifier, the selector and
the strategies — but not `_abstract_reasoning`, which is the code the fix
changed. The test would have passed identically with the fix reverted. Same
mistake as verifying a memory write with a spy that never writes.

Re-verified through the REAL path — `bridge.reason(ReasoningRequest(mode=ABSTRACT))`
-> `_abstract_reasoning` -> engine — supplying only what a caller supplies, a
query and its context, and OBSERVING what the engine was asked for rather than
arranging it:

    QUERY                          ALLOWED  PREM  SELECTED         LLM
    why did the checkout time out?       1     2  CAUSAL             0
    is the chip inside the board?        1     2  SPATIAL            0
    how full is the disk, roughly?       1     2  FUZZY              0
    does the lock always hold?           1     2  TEMPORAL           0
    what would have happened without…    1     2  COUNTERFACTUAL     0

    routed correctly through the real bridge path: 5/5

The two middle columns are what prove the fix is load-bearing rather than
decorative: `ALLOWED=1` means the classifier narrowed the eleven to exactly the
kind the query asked for, and `PREM=2` means request context reached the engine
as premises. Before the fix those columns read 3 (the hardcoded list) and 0.

131 tests pass.

---

### Defect 28 — substrate-first was a MODE, not the architecture — FIXED 2026-08-24

`_substrate_first` was called inside `if request.mode == ReasoningMode.AUTO`.
Every other mode — SYMBOLIC, NEURAL, HYBRID, NEURO_SYMBOLIC, ABSTRACT,
CROSS_DOMAIN — went straight to `run_mode()` and never asked whether Torin could
represent the input itself.

So naming a mode was, without the caller knowing it, **asking for the substrate
to be skipped**. "Substrate-first" described one of seven routes rather than the
architecture, and six of the seven were model-first.

**Whether Torin can settle something from its own rules is not a routing
preference.** It is the first question, and the answer does not depend on what
the caller guessed the work would need. `mode` now says only what to do WHEN THE
SUBSTRATE CANNOT SETTLE IT — AUTO meaning "choose for me", the others naming the
fallback. It never means "do not ask".

Nothing is lost by asking first: `_substrate_first` returns None the moment
deterministic formalization fails and probes only the model-free formalizers, so
an input Torin cannot read costs one failed parse before the requested mode runs
exactly as before.

**Verified — the same settleable query through all seven modes:**

    MODE             ANSWER                CONF  VERIFIED  LLM
    symbolic         'Proved: odin_black'  0.98      True    0
    neural           'Proved: odin_black'  0.98      True    0
    hybrid           'Proved: odin_black'  0.98      True    0
    neuro_symbolic   'Proved: odin_black'  0.98      True    0
    abstract         'Proved: odin_black'  0.98      True    0
    cross_domain     'Proved: odin_black'  0.98      True    0
    auto             'Proved: odin_black'  0.98      True    0

A caller who explicitly asks for NEURAL now receives a Z3 refutation proof,
because the substrate could settle it. Before this change that request went
straight to the model.

**Still open — the seven are the wrong vocabulary for an entry point.**
SYMBOLIC / NEURAL / HYBRID / NEURO_SYMBOLIC is the neuro-symbolic framing: a
taxonomy of WHICH MACHINERY RUNS, with one member named after the model. The
eleven kinds of thinking are still invisible from outside — `ReasoningRequest`
has no way to ask for causal or temporal reasoning, and the eleven are reached
only when the router happens to select ABSTRACT. Naming these seven for what they
are (execution routes) and letting a caller name a KIND of thinking is the
remaining work.

131 tests pass.

---

### Defect 29 — the eleven kinds were unreachable from the entry point — FIXED 2026-08-24

`ReasoningRequest` could only name one of seven execution ROUTES. There was no
way to ask for causal or temporal reasoning, and the eleven were entered only
when the router happened to select ABSTRACT — on `is_abstract` keyword markers
that say nothing about whether a question is causal. Eleven kinds registered and
implemented; nine of them unaskable.

**Fix, in four parts.**

1. `ReasoningMode`'s docstring now says what it is: WHICH MACHINERY RUNS WHEN
   THE SUBSTRATE CANNOT SETTLE IT. Not kinds of thinking. The
   SYMBOLIC/NEURAL/HYBRID/NEURO_SYMBOLIC vocabulary is the neuro-symbolic
   framing, a taxonomy of implementation with one member named after a model.
   Kept, because each names a real handler and a caller may want to choose the
   fallback — but it is no longer what an entry point asks for.
2. `ReasoningRequest.kinds: List[ReasoningType]` — a caller names kinds of
   thinking. Empty means "read it from the query".
3. `_reason_by_kind()` runs **after `_substrate_first` and before any execution
   route**. That order IS the architecture: what Torin can prove, then what
   Torin can derive, then what a model can propose. It returns None — not an
   empty result — when no kind applies, so "no kind fits this" stays
   distinguishable from "a kind ran and found nothing"; only the first should
   reach a model.
4. Context is split by what each item IS. A flat list of strings was not enough:
   abduction searches `context.rules` backwards and deduction fires over them,
   so an item that is an implication must arrive as a RULE. Passed as a premise
   it is inert — measured, "what best explains the wet lawn?" with
   `rained -> lawn_wet` in context reached the model while abduction sat
   applicable and unused. The query becomes `target_conclusions`, because
   logical and probabilistic reasoning both need a claim to settle.

### Defect 30 — a propositional refutation buried the answer — FIXED 2026-08-24

Found while testing the above. `_substrate_first` formalizes PROPOSITIONALLY, so
relations become opaque atoms:

    "the chip is inside the socket"   ->  chip_inside_the_socket
    "the socket is inside the board"  ->  socket_inside_the_board
    "is the chip inside the board?"   ->  chip_inside_the_board

Three unrelated symbols. The solver correctly reported `substrate_refuted` —
"Not entailed by the premises" at confidence 0.0 — and returned, so the eleven
kinds never ran. `SpatialReasoningStrategy` derives the answer in one step,
because containment composes and atoms do not.

Correct about the propositions it was handed. Wrong about the world.

**Fix: a refutation obtained through a lossy reading is DEFERRED, not returned.**
"I proved it" is final; "I could not derive it from this reading" is a fact about
the reading. The refutation is kept and returned if no kind of thinking settles
the question — never discarded.

**And the first version of that fix was too broad, which a test caught.**
Deferring EVERY refutation let a weaker derivation displace a sound one:
`mortal` from premises `["human"]` genuinely does not follow, nothing relational
is lost, and that refutation must stand. The deferral now applies only when the
query carries a marker for a kind of reasoning atoms cannot express —
containment composing, causes chaining, degrees, time order. An unmarked query
keeps its refutation.

**Verified through the DEFAULT entry point** — no mode named, no kinds named,
only a query and its context, with the kind that answered read from the result:

    why did the checkout time out?              causal          1.00  llm=0
    what would have happened without the retry? counterfactual  0.50  llm=0
    is the chip inside the board?               spatial         1.00  llm=0
    how full is the disk, roughly?              fuzzy           1.00  llm=0
    does the lock always hold?                  temporal        1.00  llm=0
    how likely is the disk failing?             probabilistic   1.00  llm=0
    generally these swans tend to be white      inductive       0.30  llm=0
    what best explains the wet lawn?            abductive       0.35  llm=0
    this is similar to the pump                 analogical      0.57  llm=0

    answered by the expected kind: 9/9      route: substrate_first -> kinds_of_thinking -> <kind>

Proofs still short-circuit correctly: the syllogism returns
`Proved: odin_black` at 0.98 through all seven modes with 0 model calls.

`REASON_DERIVED_BY_KIND` is a new reason on the credit-assignment contract,
distinct from `SUBSTRATE_VERIFIED` on purpose — that means a solver checked a
formalized statement, this means a strategy composed the conclusion from the
premises. Both are the substrate answering; they are not the same evidence.

131 tests pass.

---

### Defect 31 — three low confidences, three different causes — FIXED 2026-08-24

Noticed by asking why induction scored 0.30 and abduction 0.35. Neither number
was reporting what it appeared to.

**(a) The question was being treated as an observation.** `_reason_by_kind`
passed `facts=[request.query]`, and `AbductiveReasoningStrategy._observations`
reads premises PLUS facts — so "what best explains the wet lawn?" became
something to be explained. Nothing explains a question, so
`coverage = 1/2` and every abductive conclusion was scored at exactly HALF its
value: **0.35 where the formula gives 0.70**. The conclusion was right and only
its confidence was wrong, which is the kind of error nothing reports.

Counterfactual was undercounted the same way: **0.50 -> 0.67**.

**(b) Emptying `facts` broke counterfactual, which needs it.** The first fix
removed `facts` entirely; `CounterfactualReasoningStrategy.is_applicable`
requires them — there is nothing to compare an alternative against without the
conditions that actually hold — so every counterfactual became inapplicable and
went to a model. Facts are now the stated context minus the question. Safe to
repeat the premises there: `_observations` deduplicates on statement text.

**(c) Induction's confidence was `len(premises) / 10.0`.** Divide by ten. The
ten had nothing behind it — not an interval, not a posterior, not a rate. It
asserted that three examples are worth 0.30, and that number went into memory
and ranking as though it meant something.

Replaced with **Laplace's rule of succession**, which answers exactly this
question: given n observations of a kind and no counterexample, the posterior
mean that the next is the same is `(n + 1) / (n + 2)` under a uniform prior.

    n = 1 -> 0.67    n = 2 -> 0.75    n = 3 -> 0.80    n = 9 -> 0.91

It has the shape induction should have: never certain however many cases are
seen, never below a half, because a run of confirmations is evidence even when
short. `logical_validity` was a hardcoded 0.6 that no count could move; it now
tracks the same evidence.

### Defect 32 — induction counted its counterexamples as support — FIXED 2026-08-24

I first recorded this as "induction does not look for counterexamples". That was
too generous, and wrong about where they go.

**They are not in another group. They are in THIS one, counted as support.**
`_premises_are_similar` groups on word overlap > 0.3, and "swan d is black"
scores 2/6 = 0.33 against "swan a is white" — so it is grouped WITH the
positives. The pattern (words in >=70% of the group) then drops the contested
colour, and the generalisation is drawn over contradicting evidence with every
member counted as confirmation. A disconfirmation did not merely go unchecked;
it moved the number the wrong way.

The real inducer in `core/learning/rule_induction.py` has always done this
properly — `contradicted_by`, `CONTRADICTORY_EVIDENCE`, and a refusal when
"every generalization of these demonstrations also covers a
counter-demonstration". This second, weaker induction did not, which is the
duplicate-authority shape again: two implementations of one capability, only one
of them correct.

**Fix, in two parts.**

1. A member SUPPORTS the pattern only if it carries every pattern term and no
   negation. Otherwise it is a counterexample, and Laplace is applied in its
   general form: `(supported + 1) / (supported + contradicted + 2)`. The earlier
   `(n + 1) / (n + 2)` is the special case where contradictions are zero, which
   was being assumed rather than established.

2. **Split on the CONTESTED term**, because an even split hides itself. With two
   white swans and two black, neither colour reaches 70%, both drop out of the
   pattern, and it degrades to "swan is" — which every member satisfies, so
   nothing contradicts it. Evenly divided evidence scored **0.83, higher than
   three-white-one-black**. A contentless generalisation cannot be
   contradicted, and that is exactly what made it look strong.

   A contested term is one carried by at least two members but not all: a
   property the group actually disagrees about. Terms appearing exactly once are
   instance labels — the "a", "b", "c" of "swan a" — and a group is not divided
   by its members having different names.

Measured:

| evidence | before | after |
|---|---|---|
| 3 white, no counterexample | 0.80 | 0.80 |
| 3 white + 1 black | 0.80 | **0.67** |
| 3 white + "swan d is not white" | 0.80 | **0.67** |
| 2 white, 2 black | **0.83** | **0.50** |
| 9 white | 0.91 | 0.91 |

The ordering is now the right way round: evenly split below three-to-one below
unanimous. 131 tests pass.

    inductive       0.30 -> 0.80
    abductive       0.35 -> 0.70
    counterfactual  0.50 -> 0.67

9/9 through the default entry, 0 LLM calls, 131 tests pass.

---

## What the reasoning work is verified against — 2026-08-24

Stated explicitly because two of the verifications in this document were
originally done the wrong way, and the distinction decides what the numbers mean.

**REAL — through `bridge.reason(ReasoningRequest(query, context))`, default
mode, nothing constructed by hand, results read back off what the bridge
returns:**

- All 11 kinds reached from a plain question — 9/9 on the cases with material,
  0 LLM calls, route `substrate_first -> kinds_of_thinking -> <kind>`
- All 7 execution routes returning the substrate's proof (`Proved: odin_black`,
  0.98, verified) with 0 model calls
- Counterexample handling: unanimous 0.80, three-to-one 0.67, evenly split 0.50,
  nine unanimous 0.91 — with the Laplace arithmetic visible in the returned
  `reasoning_steps`
- **Persistence: a real row in `memory_hot.memory_hot`.** A causal derivation
  from a plain query stored as `mem_ea49...`, importance 0.84, tags
  `["reasoning", "abstract", "causal"]`, then cleaned up. Success measured as a
  ROW, not a return value.

**NOT REAL — strategy or engine called directly with a hand-built
`ReasoningContext`.** Useful as unit tests of a strategy; they prove nothing
about wiring, and a fix verified only this way would pass with the fix reverted:

- the first 11/11 routing result
- the per-strategy spatial/fuzzy/causal checks
- the first counterexample check (since re-done through the real path)

**Defect 33 — the record could not say what kind of thinking produced it —
FIXED.** Found by the persistence test. `_capture_reasoning_memory` tags with
`mode_used`, the execution ROUTE, so every kind-derived conclusion was stored as
`"abstract"`: a causal derivation and a spatial one were indistinguishable in the
record, and nothing could later ask what Torin had concluded causally. The kind
is now tagged alongside the route.

### Does reasoning survive a restart? Yes — tested with separate processes.

Not a fresh object in the same process; two genuinely separate interpreter runs.

**Process 1** reasoned causally from a plain query and persisted:

    P1 kind=causal conf=1.00 answer='disk exhaustion causes zq041fdfe81f fail'
    P1 persisted rows: 1

**Process 2**, a cold start after process 1 exited:

    P2 found 1 row written by the previous process
       mem_95e2...  tags=["reasoning", "abstract", "causal"]
    P2 validated rules available: 5
    P2 fresh reasoning: kind=spatial conf=1.00 llm=0

So three separate things survive, and they are worth separating:

| what | where | survives |
|---|---|---|
| conclusions | `memory_hot.memory_hot` | yes, with the kind tagged |
| the rules reasoned FROM | `unified.learned_rules` | yes, 5 validated |
| the strategies | code, re-registered at startup | yes |
| per-query working state | in-memory, recomputed | no, and correctly so |

That last row was worth checking rather than assuming, because
`temporal_reasoning` owns `_save_future_state` and its own tables — repeated
reasoning could have accumulated propositions and causal links without bound.
Measured over five identical calls:

    unified.temporal_propositions     0 -> 0
    unified.causal_links              0 -> 0
    unified.future_states             0 -> 0
    memory_hot.memory_hot           906 -> 906
    unified.learned_rules            12 ->  12

Nothing accumulates. The propositions a causal query builds are working state
derived from its premises and are rebuilt each time, which is right — they are
not knowledge, they are the derivation. And `memory_hot` holding steady across
five IDENTICAL calls is deduplication working, not a failure to store: the same
query with a novel marker stores a row every time.

169 reasoning and memory tests pass.

---

## Memory work — started 2026-08-24

### Corrections to earlier readings in this document

**The memory agent IS the authority, and IS used.** `memory_injector` delegates
retrieval to `memory_agent.search_memories`. It is a formatter and placement
helper, not a second store. An earlier reading here implied the bridge reached
around the agent; it does not.

**Relevance is already single-authority.** `MemoryInjectionPolicy.decide()` is
consulted by the injector, the coordinator and the executor, with
`test_memory_injection_authority.py` enforcing the invariant it states:
*one policy decides whether and what memory enters cognition; many consumers
decide only where it goes.*

**Nothing is "undone" by the prose rendering.** Structure survives in the store
and is present in what retrieval returns. It is dropped at one boundary — the
injection result — and `memory_ids` is carried, so it is a round trip away
rather than lost. An earlier claim in conversation that the memory path would
undo the reasoning work was wrong and is withdrawn.

### Defect 34 — a memory blob became a single premise — FIXED

Introduced today, by the reasoning work. `_reason_by_kind` turns
`request.context` into premises, and the bridge inserted memory as ONE string: a
header sentence followed by every retrieved memory as bullets.

Measured harm, on the real strategies:

    [1.00] 'you have access to the following relevant context from memory:
            • disk exhaustion causes ...'
    [1.00] 'root cause of checkout timeout • the retry is inside the request
            handler: you have access to ...'

Fabricated causal links at **confidence 1.00**, with a prompt header as the
cause, headed for the memory store as derived knowledge. Exactly the fabrication
the architecture exists to prevent, opened by a change made hours earlier.

The rule that was missing: **one context item, one claim.** A prompt wants one
blob; every other consumer wants one statement per item.

- `InjectedMemories.records` carries the memories as separate claims, in the same
  order as `memory_ids`. `formatted_text` is unchanged and still right for a
  prompt — neither replaces the other.
- Both injection paths insert claims individually. The second path — cached
  memories, building `"PREVIOUS RELEVANT WORK:"` plus bullets — had the same
  defect and is fixed the same way, including dropping the `- ` bullet marker,
  which was formatting for a prompt and became part of the statement everywhere
  else.

### What the measurements showed about memory reaching cognition

    query                                          enabled  memories  records
    "why did the deployment fail?"                   False         0        0
    "why did the checkout time out after the disk
     filled and the retry did not fire?"              True         1        1
    "analyse the failure modes of the pool..."       False         0        0
    "list files"                                    False         0        0

Simple queries are declined by `COMPLEXITY_FLOOR = 0.35`, which is the policy
working — "list files" should not pull memory. The bridge additionally requires
`min_relevance_score=0.6`, stricter than the injector's default, so a memory can
be retrieved standalone and still not reach reasoning.

### Defect 2 — recall handed back documents, not claims — FIXED 2026-08-24

**First, a correction: storage was never the problem.** An earlier reading here
said a reasoning trace was "rendered away". It is not. The row keeps it:

    reasoning_trace: ["Identified pattern: swan is white",
                      "Generalized from 3 supporting example(s)",
                      "no contradicting example in this group",
                      "Laplace: (3 + 1) / (3 + 0 + 2) = 0.80"]
    tags:            ["abstract", "reasoning", "multi_step"]

A dedicated column, populated, with the derivation and its arithmetic intact.
The prose in `content` is a DUPLICATE of that, not a replacement. No storage
format change was needed and none was made.

**Nor was forwarding the trace the answer.** A trace step reads
`"link strength 1.00"` — a measurement OF the reasoning, not something that is
the case. Handing those to a reasoner as premises would be no better than
handing it the document.

**What a past conclusion contributes to later reasoning is the CONCLUSION.**
Recall should hand back "disk exhaustion causes checkout timeout", not a
document about having concluded it. The writer has that string in hand at the
moment it is known, so it is stored then rather than parsed back out of prose
later:

    source_context.conclusion             the claim
    source_context.conclusion_confidence  what it was worth
    source_context.conclusion_kind        which kind of thinking produced it

Recall prefers `claim` when the record carries one and falls back to `content`
when it does not — which is most older records, and every memory that is an
episode rather than a conclusion. `reasoning_trace` is now carried through
retrieval too; it was read out of the row already and was simply being dropped.

**Verified end to end, real path:**

    wrote conclusion: 'disk exhaustion causes zqfd892ec9 write failure'
    persisted:        1 row
    recalled:         CLAIM 'disk exhaustion causes zqfd892ec9 write failure'

A single statement rather than a `"Query: ... / Reasoning steps: ... / Answer:
..."` document.

### Things checked along the way that turned out to be fine

**Fresh memories are recallable.** Written, embedded, and found by exact text,
by paraphrase, and by a query containing none of its distinctive terms. An
earlier zero result was the injector's own relevance gate, not a storage or
recall failure — `search_memories` finds it every time.

**A zero from `inject_memories` is usually the policy working.**
`COMPLEXITY_FLOOR = 0.35` declines "list files", and the bridge additionally
requires `min_relevance_score=0.6`, stricter than the injector default. So a
memory can be retrievable and still not reach reasoning, by design.

### Still open

**182 of 258 reasoning memories have no `reasoning_trace`.** They come from
paths that do not populate it. Any consumer reading that column gets structure
for some records and nothing for others, and must handle both. Worth finding
which paths those are before relying on it.

**Older memories carry no `conclusion`.** The claim path applies to records
written from now on; the 906 already stored fall back to `content`. No migration
was attempted, and none is needed for correctness — only for coverage.

---

### Defect 3 — the executor held reasoning machinery it never used — FIXED 2026-08-24

Two dead things, and one false claim on every start.

`self.neural_bridge` was constructed, initialised, and logged
`"✓ Neural bridge connected - reasoning traces will be automatically captured"`.
It appeared nowhere else except its own assignments. No trace was captured by
that path, and the log said otherwise every time the executor started.

`cached_memories = unique_memories`, commented "Store for passing to neural
bridge", was never passed anywhere — the executor does not call the bridge.

Both removed. **The memory retrieval itself is NOT wasted**, which is worth
stating because it looks like it should be: the same memories are formatted a
few lines below into `previous_context`, which does reach the prompt at
`:1977`. Only the bridge hand-off was dead.

The executor EXECUTES. Reasoning is entered through the bridge by callers that
reason, and the bridge records its own traces — verified landing in the memory
store with the kind of thinking tagged.

54 executor, rule-authority and memory tests pass.

### Defect 9 — `understand()` and `say()` gave different answers — FIXED 2026-08-24

A question about the conversation itself is answered from the record, in
`understand()`, because nothing else can answer it: the sentence is not about
the world, so there is nothing to resolve. `say()` then recomputed a reply from
`known` and `unknown`, both empty in that case, and produced a second answer:

    understanding.reply  ->  "We were talking about harrier."
    say(understanding)   ->  "There was nothing in that I could resolve"

Two ways to get one answer, disagreeing, with the worse one derived over an
empty result. `say()` now returns an answer already established rather than
re-deriving it. Verified: both paths return `"We were talking about harrier."`

### The two pre-existing failures — BOTH FIXED 2026-08-24

Neither was caused by the memory work. Both were real, and one of them was a
defect in the code rather than in the test.

**`test_genericity` — a locative bypassed the genericity gate. CODE WAS WRONG.**

That test guards a stated risk: reading the article `a` as a quantifier turns
"A robin is in the yard" into a law about all robins — *"an overgeneralization
machine that proves things nobody said"*. `Genericity.EXISTENTIAL` is
deliberately NOT representable: the formal grammar has no existential
quantifier.

The prepositional branch returned `{"kind": "relation", "genericity": "n/a"}`
and never called `classify_genericity`, which runs further down and was never
reached once a preposition matched. So "A robin is in the yard" became
`in(robin, yard)` — reading `robin` as a named individual when the sentence says
SOME robin. The existential quantification was dropped silently.

The same failure the genericity stage exists to prevent, arriving from the other
side: not "all robins are in the yard" but "robin, the thing, is in the yard".

Fixed by classifying before returning a relation. A definite or proper subject
reads as INSTANCE and still works — "the cup is in the top cabinet" names a cup,
which is the case the prepositional pattern was added for.

**A second authority found while fixing it.** The refusal had two names: the
original decline site emitted the marker
`existential_quantification_not_supported`, and the new gate invented its own
prose — so the same refusal was greppable by one name and not the other.
`unrepresentable_reason()` now owns the marker and both sites use it. 29/29 pass.

**`test_derived_reading` — the TEST was outdated, by a real capability gain.**

Its premise was that `vault holds gold` has no copula and no pattern covers a
bare subject-verb-object form. One does now: `_SVO` reads SVO when the SUBJECT
is a known noun, on the reasoning that the word standing after a known thing is
the action — *which is how a learner meets a new verb*. Requiring the verb's
class first made verbs unlearnable, since the only way to learn a verb is to
read a sentence using it.

Once `vault` entered the lexicon as a NOUN, the written patterns could read the
sentence and the test's premise stopped being true.

Changed to `quorn holds gold` — not in the lexicon, so no anchor, so the SVO
pattern declines exactly as the six patterns declined the original. Verified
both ways: with `vault` the extractor reads `vault_holds_gold`; with `quorn` it
declines. The test's purpose is intact and the reason for the change is recorded
in it, so it does not read as having been weakened. 5/5 pass.

**Noted, not fixed:** the two readers disagree on the atom for the same
sentence — the written path yields `<subject>_<verb>_<object>`, the derived path
`<subject>_<object>`. They are separate readers and the chain prefers the
written one, so it only matters where both apply.

121 semantics, conversation, lexicon, reading and genericity tests pass.

---

## Reading has no single authority — 2026-08-24

Asked directly: why are there two readers, and where is the authority? There are
THREE, in two faculties, and there is no declared authority.

| reader | lives in | reads a sentence into |
|---|---|---|
| `read_claim` | `core/semantics/claim_shape.py` | subject, property, polarity, tense — at memory write time |
| `DeterministicExtractor` | **`core/reasoning/neural_bridge.py`, 619 lines** | fact / svo / sv / relation / universal — for reasoning |
| `DerivedReading` | `core/semantics/reading_registry.py` | a LEARNED procedure |

**619 lines of hand-written English patterns live inside the reasoning module**,
while the language faculty sits next door with 2,995 lines across ten files. And
the memory and reasoning work in this document treated that as a given — the
locative genericity gate was ADDED to those patterns today without asking
whether they should exist. That was a miss, and it is recorded as one.

### The learned reader was not reachable from reasoning

`ensure_registered()` — which derives the reading and puts it in the registry —
is called from **exactly one place**, `conversation.py:690`. In a reasoning-only
process the registry is EMPTY, `DerivedReadingFormalizer` finds nothing, and the
hand-written patterns are the only reader there is.

So the learned reader was not losing to the patterns. It was not in the room.

### Measured: the learned reader is broader, and lacked the discipline

Same nine sentences, both readers, after registering the derived reading:

| sentence | patterns | derived |
|---|---|---|
| a robin is a bird | — | `robin_bird` |
| the vault is locked | `vault_locked` | `vault_locked` |
| copper is not brittle | `~copper_brittle` | `~copper_brittle` |
| sparrow is a bird | `sparrow_bird` | `sparrow_bird` |
| the turbine is hot | `turbine_hot` | `turbine_hot` |
| quorn holds gold | — | `quorn_gold` |
| the pump moves water | `pump_moves_water` | `pump_water` |
| a robin is in the yard | — | **`robin_yard`** |
| all humans are mortal | — | — |

Derived 8/9, patterns 5/9 — and the eighth was the problem. **`robin_yard` is the
exact existential defect corrected in the patterns hours earlier**, reading
`robin` as a named individual when the sentence says SOME robin. Removing the
hand-written patterns at that point would have reintroduced the
overgeneralisation through the other reader.

### Defect 35 — a derived reading skipped representability — FIXED

The reading says WHAT a sentence relates; genericity says whether the formal
grammar can carry that relation. Separate stages, and the second was not run on
derived readings.

Now it is. **No pattern was added and no wording knowledge introduced** — the
representability rule the substrate already owns is applied to whatever the
reading produced.

**One bug in that fix, caught by measuring rather than assuming.** Genericity is
decided on the complement AS WRITTEN: `("robin", "a bird")` classifies as a kind,
`("robin", "bird")` as AMBIGUOUS and refuses. Passing the bare object rejected
"a robin is a bird" — a perfectly representable statement about kinds. The
complement is now taken from the sentence, dropping a leading copula or negator
using the vocabulary `core/semantics` already owns.

Final state — the learned reader has the breadth AND the discipline:

    a robin is a bird       -> robin_bird     (generic kind, representable)
    quorn holds gold        -> quorn_gold     (a form no pattern covers)
    a robin is in the yard  -> declines       (existential, correctly refused)

    derived 7/9   patterns 5/9

97 reading and reasoning tests pass.

### What this makes possible, and what it does not

Removing the hand-written patterns is now a viable direction rather than a
regression — the learned reader exceeds them on this set and refuses what it
should. It is NOT done, and should not be done on nine sentences: the 619 lines
also cover universals, conditionals, questions, conjunctions and SVO, and what
share of those the derived reading handles has not been measured.

### RESOLVED — semantics owns reading (2026-08-24)

Decided, and carried out. Reading left the reasoning module.

| moved to | what | lines |
|---|---|---|
| `core/semantics/sentence_reader.py` | `SentenceReader` — the patterns, `_parse_statement`, `_read_copular`, `_parse_goal`, the renderers, morphology | 406 |
| `core/semantics/genericity.py` | `Genericity`, `classify_genericity`, `unrepresentable_reason`, `_word_class`, the locative vocabulary | 238 |

`neural_bridge` keeps the FORMALIZER — turning a reading into the statement and
premises a solver takes — and imports the rest. That is the boundary: reasoning
consumes a reading; it does not implement one.

**Verified identical before and after.** The same nine sentences produce the same
results through both readers, patterns 5/9 and derived 7/9, with the existential
still correctly refused. The move changed where the code lives, not what it does.

**Three transcription faults, each caught by running rather than reading:**

- `@dataclass(frozen=True)` was lost on `GenericityReading` — an AST class span
  starts at `class`, below its decorator. It failed loudly (`takes no
  arguments`), which is the good case.
- Two helpers, `_is_locative` and `_leading_word`, were referenced and left
  behind. Found by walking the moved modules for names defined only in the
  bridge, rather than by discovering them one exception at a time.
- A blanket `self._atom(` rewrite reached into `DerivedReadingFormalizer`, which
  owns its own `_atom`. Scoped to the one class and reverted.

**Three test files were pointing at the old owner** — `test_genericity`,
`test_lexical_normalization` — reaching into `DeterministicExtractor._parse_statement`
and `._singular`. They now import from the modules that own those things. Worth
noting how this could have gone wrong quietly: `neural_bridge` still re-exports
the moved names, so a test could keep passing while testing the wrong owner.
That is how an import outlives the architecture it was written for.

**250 semantics, conversation, lexicon, reading, genericity, reasoning and
memory tests pass.**

### The coverage measurement — and it reverses the earlier reading

Measured against the real system, and the result contradicts what "derived 7/9
vs patterns 5/9" appeared to show.

**That earlier number measured the wrong thing.** It counted whether a reader
PRODUCED A STATEMENT, not whether the statement was usable. The honest question
is whether the solver can settle the goal from what the reader produced.

Each form exercised the way it is actually used — universals and conditionals as
PREMISES, questions as GOALS, every case with something real to prove:

| form | patterns settle | derived settle |
|---|---|---|
| universal | 2/2 | **0/2** |
| conditional | 0/2 (no reading) | **0/2** |
| question | 2/2 | 0/2 (no reading) |
| conjunction | 1/1 | **0/1** |
| fact | 1/1 | 1/1 |
| **total** | **6/8** | **1/8** |

**Why derived fails despite "formalizing" successfully.** It is a COPULA-ATOM
reader: it maps a sentence to `subject_object` with a polarity, which is exactly
what it was taught from sentence/meaning pairs. So "all humans are mortal"
becomes a flat atom rather than the implication
`socrates_human -> socrates_mortal`, and the solver has no rule to work with.
Visible in the premise counts before the proof was even attempted —
`socrates_mortal <= 2p` from the patterns against `<= 1p` from the derived
reading. The rule was missing.

It also cannot read a question at all, and on a conditional it produced
`if_fail` — a WRONG reading rather than a refusal, taking "if" as the subject.

**So the hand-written patterns are not redundant scaffolding.** They carry
structure the derived reader has never been taught: universals as implications,
questions as goals, conjunctions as several claims. Removing them would break
five of eight cases.

**This changes what "no hand-written patterns" requires.** Not a deletion — a
TEACHING problem. The derived reader would have to learn to read a universal as
an implication, a question as a goal, and a conjunction as more than one claim.
That is the same reading problem named as the binding constraint throughout this
document, and the patterns are what stands in for it until the teaching is done.

The move to `core/semantics` was still right and is unaffected: reading belongs
to the language faculty whether it is derived or written. What changed is the
expectation of how soon the written half can go.

---

### Teaching the reader — questions taught, 2026-08-24

The measurement said the derived reader settled 1 of 8. The first question was
whether that is a teaching problem or a capability problem, and the answer
differs by form.

**Questions were a TEACHING problem, and are now taught.** "Is the vault locked?"
and "the vault is locked" relate the same two things and differ only in what the
asker wants done with the claim — and which is the query is decided by POSITION
at formalization, not by grammar, so a reading need not mark the form at all.

The machine could always express it: SKIP(is), SKIP(the), BIND_SUBJECT,
BIND_OBJECT, EMIT. Nothing had ever asked it to, because every taught sentence
put the subject first, so no procedure covering them had to handle a sentence
OPENING with a copula.

Three pairs added to `TAUGHT`. The reading was re-derived and now reads
questions it was never taught:

    is the vault locked?   ->  ('vault', 'locked', 'affirms')     taught
    is Odin black?         ->  ('odin', 'black', 'affirms')       HELD OUT
    is a robin a bird?     ->  ('robin', 'bird', 'affirms')       HELD OUT
    is the turbine hot?    ->  ('turbine', 'hot', 'affirms')      HELD OUT
    the vault is locked    ->  ('vault', 'locked', 'affirms')     unchanged

No pattern was written. Three examples, and the form generalised. Solver
coverage 1/8 -> 2/8, and 97 tests pass.

**Universals are NOT a teaching problem, and this is the useful finding.** The
reading of "all humans are mortal" as `(humans, mortal, affirms)` is correct —
what is missing is that it is a UNIVERSAL, so the formalizer can render it as
the rule `socrates_human -> socrates_mortal` rather than the atom
`humans_mortal`. The reading is right and the FORM is unavailable.

The machine cannot observe the form because quantifiers are not in its
vocabulary. Its whole supplied lexicon is six words — `is/are`, `a/an/the`,
`not` — and it flags a word as COPULA, DETERMINER, NEGATOR or CONTENT. `all`,
`every` and `no` fall through to CONTENT, indistinguishable from `humans`.

So universals need the vocabulary extended and a form carried out of the
reading, which the current `(subject, object, polarity)` triple cannot hold.
That is a real extension, and it is the same kind of thing COPULAS and NEGATORS
already are — declared function-word classes, not sentence patterns.

**Conditionals are the same shape**: `if` and `then` are also CONTENT to the
machine, and a conditional relates two CLAIMS rather than two terms, which a
triple cannot express either. The derived reader currently produces `if_fail`
for one — a WRONG reading rather than a refusal, taking `if` as the subject.

**Conjunctions likewise** need to emit more than one claim.

**The order this implies**, by value and by dependency: universals first — they
block three cases, since a question over universal premises fails on the
premises. Then conjunctions, then conditionals.

    form          patterns   derived   blocked by
    universal        2/2       0/2     quantifier vocabulary + form in the reading
    conditional      0/2       0/2     if/then vocabulary + two-claim output
    question         2/2       1/2     TAUGHT (done); remainder blocked by universals
    conjunction      1/1       0/1     two-claim output
    fact             1/1       1/1     --

---

### Defect 10 — WRONGLY DIAGNOSED, corrected 2026-08-25

Earlier entries called this "the operator binding registrar does not exist" and
treated it as wiring. Measured, it is not.

**No learned action corresponds to any real tool.** The rule store holds four
action predicates and the registry holds 372 tools, and they do not intersect:

    MOVE      -> no tool of that name
    KEM       -> no tool of that name
    RELOCATE  -> no tool of that name
    TRANSFER  -> no tool of that name

Every rule was induced in a synthetic domain — kite17, warehouse, syllogism. The
substrate has never learned a rule over an action it can actually perform, so
there is nothing for a registrar to bind even if one existed.

**And the path that would produce such a rule cannot start.** A real execution
becomes a demonstration through `_record_execution_demonstration`, which is
called from exactly ONE place: inside `_try_substrate_execution`. So —

    a demonstration over a real tool
      needs the substrate path to run
        which needs a binding
          which needs a rule whose action is a real tool
            which needs a demonstration over a real tool

The model-backed path, where every real tool execution actually happens today,
records no demonstration at all.

**Why "just record on the model path too" does not work.** A demonstration is
`(before, action, after)` — observed world state either side of the act. The
model path has no way to READ the world; observation comes from the binding's
`observe`, which is the thing that is missing. The gap is not the executing half
of a binding but the observing half.

**So it must be DECLARED, and `experiments/e2e_world.py` already shows exactly
what a declaration is:**

    predicate   MOVE
    tool_name   move_file              <- a real, registered tool
    parameters  how MOVE's args become that tool's arguments
    observe     how to read the relevant world
    description "rooms are directories; the agent is a file"

About twenty lines, and it cannot be inferred: nothing in a tool's declaration
says which learned predicate it performs, or what counts as the world it
changes. That is a modelling decision about a domain.

### THE DEADLOCK CLAIM ABOVE IS WRONG. Refuted by running the system.

Everything above this line was reasoned from code reading and is retained as a
record of the error. `tests/test_computational_execution.py` refutes it, and it
passes today:

- it induces rules over real tool actions and PERSISTS them via
  `record_induction`
- it registers a world binding
- it runs **`GeneralPurposeExecutor().execute_task(task)`** -- the production
  executor, not a test double
- it asserts `success=True`, `runtime_outcome=CONFIRMATION`, `model_free=True`
- and it checks real files: `TEXT("17")` -> `NUMBER("17")` -> `PRODUCT("34")` ->
  `WRITTEN("34")` on disk

`computation_world.py` states it plainly: *"EVERY ACTION IS A REAL REGISTERED
TOOL, invoked through the tool registry, and `observe()` reads the filesystem
afterwards."* READ, PARSE_NUMBER, MULTIPLY and WRITE map to `copy_file` and
`run_python`.

So the substrate DOES learn rules over actions it can perform, plan over them,
execute them through the production path with zero model calls, and change real
files. There is no deadlock, and "it has never learned a rule about an action it
can actually perform" was false.

**What is actually true, and it is one line:** nothing in `core/` registers a
world binding at startup. The only `get_binding_registry().register` call in
production code is in `sentence_machine`, and it has no callers. The
declarations live in `experiments/`, so the capability is exercised by tests and
experiments and never by a running system.

The rule store therefore holds only the synthetic domains, because the rules
learned over real tools belong to test runs rather than to a process that keeps
running.

**Method note.** The earlier diagnosis was assembled from grep and inference —
no learned action matches a tool name, `_record_execution_demonstration` has one
caller, therefore deadlock. Every individual observation was correct and the
conclusion was wrong, because none of it was run. A passing test in the same
repository contradicted it outright.

---

### Concurrency — the coordinator already handles multiple internal tasks

Raised because a stale comment said otherwise, and the correction matters for
how substrate execution attributes what it observes.

**One instance, one user.** TorinAI runs as a single instance behind one
fingerprint-guarded door. Multi-user isolation is not a concern here, and an
earlier reading that framed the global binding registry as a data-isolation risk
was answering a question this deployment does not ask.

**The internal task queue is not external requests.** The coordinator IS the
substrate; running several internal tasks at once is what a mind doing several
things looks like, not a hazard to be designed away.

**It already does, and it is real rather than nominal.** Measured through the
production `TaskExecutionPool`:

    3 tasks x 0.4s each
    wall clock      : 0.40s   (serial would be ~1.2s)
    peak concurrent : 3
    interleaving    : t0:start t1:start t2:start t0:end t1:end t2:end

`asyncio.Semaphore(max_parallel=5)` in the pool, with the coordinator gating at
`_max_parallel_tasks` (default 3), tasks launched rather than awaited, tracked in
`_inflight_tasks`, and reaped by `_reap_finished_tasks` — which also makes
reflection due on a failure rather than waiting for the next tick.

### Defect 36 — the coordinator logged "one task at a time" while running three — FIXED

    # SINGLETON MODEL: No parallel task pool. The coordinator runs one task
    # at a time; sub-agent parallelism happens within the executor.
    logger.info("Singleton execution model: one task at a time")

Printed on every start, beside `_max_parallel_tasks = 3` and a dequeue gated on
`len(self._inflight_tasks) < self._max_parallel_tasks`. It was true once —
awaiting each task blocked the whole loop, which is why reflection never ran —
and when that was removed the comment and the log were left asserting the old
behaviour.

Now states what runs, and logs the actual limit.

**What remains genuinely open, and it is not isolation.** Substrate execution
verifies a rule by observing what changed and attributes the result with
`external_interference=False` — an assumption that nothing else moved the world
during the act. With three concurrent tasks that assumption is not automatically
safe, and the failure mode is not a wrong answer but wrong EVIDENCE: one task's
change attributed to another's rule, written to the rule store as a runtime
contradiction against a rule that was fine.

The right answer is not to serialise. It is that the substrate should be able to
tell its OWN concurrent action from genuine interference — and it can, because
both executions are its own and both are recorded. `external_interference` is
answerable rather than assumed. Not yet done, and worth knowing before a world
is registered process-wide.

---

## Multi-user readiness — assessed 2026-08-25

Stated requirement: more users later; the substrate must run its own internal
work — monitoring, health, loops, security alerts — WHILE users are using it,
and it builds a profile on each user it meets.

Measured against what exists, so the gap is a list rather than an impression.

### Already there

**Internal work is already distinguishable from a user's.** `TaskSource` marks
every task as `API`, `MANUAL`, `AUTONOMOUS`, `SYSTEM` or `SECURITY_AUDIT`, and
`Task.source` carries it. Monitoring, health and security work is the
substrate's own and is already labelled as such. This is the part most systems
lack and it is present.

**Concurrency is real.** Measured: three tasks, 0.40s wall clock against a
1.2s serial baseline, peak concurrency 3. Pool semaphore 5, coordinator gate 3.
The substrate can already do several things at once while attending to a user.

**The schema anticipates tenancy.** 27 tables carry an actor column, including
`memory_hot`, `memory_cold`, `api_keys`, `auth_tokens` and every `security_logs`
partition.

### Not there

**A task has a SOURCE but no ACTOR.** `Task` records that something came from an
API and not which user sent it. Two users' requests are indistinguishable once
they are tasks, so nothing downstream — memory, evidence, rules, profiles — can
attribute them.

**The actor columns are never populated.** `memory_hot` holds 908 rows and
`user_id` is set on ZERO of them, `session_id` on zero. The columns exist and no
code writes them.

**Memory retrieval does not filter by actor.** No `WHERE user_id` anywhere in
the storage layer. Today that is harmless because there is one user; the moment
there are two, A's memories surface for B, and neither the filter nor the
injector would notice.

**There is no user-profile store.** Nothing in the database resembles one —
`profiler_results` is performance profiling, not people.

**The binding registry is keyed `(domain_id, predicate)`**, process-global, with
no actor. A world registered for one user is the world every user acts in.

### The shape of the work, in dependency order

1. **An actor on the task.** Everything else is downstream: without it, memory
   cannot be scoped, evidence cannot be attributed, and a profile has nothing to
   attach to. It is a field plus the entry points that set it.
2. **Populate and filter the actor columns.** They already exist; this is
   writing them at store time and adding the predicate at query time. The
   `MemoryInjectionPolicy` is the single relevance authority and is the right
   place for "whose memories may enter this cognition".
3. **Key the binding registry by actor** — or supply bindings per execution,
   which is the same conclusion reached from the concurrency side.
4. **Then profiles**, which are a per-actor view over memory and evidence that
   already exist, rather than a new store.

### The one that is subtle

Internal work must NOT be scoped to a user. Health monitoring, security auditing
and the idle loops are the substrate's own cognition and their memories belong
to Torin, not to whoever happened to be connected. `TaskSource` already draws
that line, so the rule is available: user-sourced work is actor-scoped, the
substrate's own work is not.

Getting that backwards in either direction is the real risk — leaking a user's
context into the substrate's own learning, or scoping the substrate's health
knowledge to whoever triggered it.

---

## Dashboard — Monitoring and Security tabs, wired to the real systems (2026-08-25)

Built end to end, no stubs. Every dot reflects a real running-state attribute
and every button moves a real subsystem.

### The cross-process problem, solved the way the app already solves it

The dashboard is a native SwiftUI app in its OWN process; the controllable
systems are live objects inside the running substrate's process. Swift cannot
call a method on an object it does not hold. The existing app already crosses
this boundary through Python + Postgres (`torin-feed --json`), so control uses
the same shape:

    STATUS   substrate --(loop)--> unified.system_control_status --> torin-systems --status --> app
    CONTROL  app --> torin-systems --control --> unified.system_control_commands --(loop)--> substrate acts

Nothing is simulated. A button writes a command row; the substrate, which holds
the objects, drains it on its loop and calls the real `start_monitoring` /
`stop` method, then records the outcome and the resulting status.

### What was built

- `core/health/system_control.py` — one authority. A registry of the eight
  systems, each with the REAL attribute that says whether it is running
  (`is_monitoring`, `monitoring_active`, `is_running`) and its real start/stop
  method. `snapshot` reads status live; `apply` moves a system; `drain_commands`
  and `publish_status` are what the substrate loop calls; `resolve_live` maps
  each system name to the exact live instance the loop uses (across the
  AutonomousSystem and its coordinator), so a green dot is the object actually
  turning, not a re-resolved singleton.
- Two tables: `system_control_commands` (queue) and `system_control_status`
  (current state per system).
- `torin-systems` — the CLI the app shells out to: `--status` and
  `--control <system> <action>`.
- `core/main.py` — `_system_control_loop`, launched with the servers, publishing
  status and draining commands every 2s off the live objects.
- `desktop/src/Systems.swift` + a tab strip in `App.swift`: Logs / Monitoring /
  Security. Coloured dots (green running, yellow stopped, blue always-on gate,
  grey absent), Stop/Restart/Start per controllable system, enabled by actual
  state. Compiled into `TorinAI Dashboard.app`.

### Honest by construction

Three security systems -- `safety_framework`, the security `controller`,
`malware_sandbox` -- are always-on gates with no lifecycle. They appear with a
status dot and NO buttons rather than a control that could not do anything.
`controllable=False` carries that from the registry to the UI.

### Verified against the real system

    registry moved security_audit_worker:  stopped -> running -> stopped
    full loop:  enqueue 'start' -> substrate drains -> stopped -> running,
                command recorded done, status published running
    gates and unknown systems refuse with a reason
    torin-systems --status -> 8 systems across monitoring + security
    torin-systems --control -> real pending row queued
    whole Swift app compiles and builds to the .app

Status when the substrate is DOWN reads `absent`/stale-with-age, which is the
honest state: nothing is turning, and the app shows the last known value with
its age rather than a live-looking dot.

### Defect 37 — the status read froze the app's main loop — FIXED 2026-08-25

Two faults, both mine, in the same read.

**It ran on the main thread.** `Systems.refresh()` spawned the status
subprocess and waited on it synchronously on the main actor, every 2s. Moved to
a detached task; only the parsed result touches main. A `refreshing` guard drops
a tick if the previous one has not returned, so a slow read cannot pile up.

**The subprocess cost 9.13 seconds.** `torin-systems` imported
`core.database`, which pulls in the whole cognitive stack -- torch,
transformers, the model runtime -- measured at 9.78s just to import, for a query
that needs none of it. Rewritten to connect with `asyncpg` directly, reading the
same env the substrate reads: **9.13s -> 0.10s**.

One correctness fix fell out of that: the direct connect defaulted user to
`postgres`, which fails, because this Postgres is trust-auth on localhost and the
substrate connects as the OS user (`stefan`). Default is now `getpass.getuser()`,
overridable by `POSTGRES_USER`. Verified: status 0.10s, control 0.11s, both
against the real database.

### The architectural note this surfaced (recorded, not yet acted on)

These tabs monitor and control systems that today run INSIDE the substrate's
process and die with it -- the inversion discussed above. The dashboard makes
that visible: stop the substrate and every dot goes absent, including the
watchdog whose job is to survive exactly that. The tabs are the right instrument
for the eventual split where monitoring runs as its own process; they will read
the same tables whether the systems run in-process or out.

---

### Dashboard panels realigned to the four concerns — 2026-08-25

The log panels were SUBSTRATE / TASKS / SECURITY / SYSTEM, with `core.health`
and `core.monitoring` buried in the SYSTEM catch-all while security had its own
panel. That asymmetry predated treating monitoring and security as peer watching
faculties.

Now **SUBSTRATE / SYSTEM / SECURITY / HEALTH**, decided by the owner:

- **SUBSTRATE** absorbs TASKS. Thinking and acting are one concern to a
  substrate-first system -- learning, reasoning, memory, then the agents,
  execution and tools that carry a decision out. A separate "tasks" lane implied
  a request pipeline the substrate does not have.
- **HEALTH** is split out of SYSTEM: `core.health`, `core.monitoring`.
- **SECURITY** unchanged: `core.security`, `core.governance`, `core.safety`.
- **SYSTEM** keeps only the machinery neither faculty owns: database, services,
  tools, api, integration.

Changed in the routing AUTHORITY (`core/observability/channels.py`) so every
reader inherits it, plus the panel metadata and the Swift enum/colors/grid.

**A hardcoded list defeated it, and had to be found by running it.** `torin-feed`
had `("tasks", "security", "system")` baked in rather than reading
`ALL_CHANNELS`, so the routing change did not reach the panels until that was
fixed -- the same second-authority defect that recurs throughout this document.
The stale `logs/channels/tasks.log` was retired; its records live under
SUBSTRATE now.

Verified: the feed serves `substrate, system, security, health`, and HEALTH
populated 200 entries immediately -- the backfill re-derives each record's
channel from its logger name, so historical `core.health` / `core.monitoring`
lines flowed into the new panel with no replay. App rebuilt.

---

## The Guardian — monitoring and security as a daemon, independent of the substrate (2026-08-25)

The dashboard controls were dead because the health and security systems were
objects INSIDE the substrate's process: stop the substrate and they cease to
exist, so nothing can start them and the loop that would execute a command is
gone too. The answer, long deferred, is that these systems must be a DAEMON, not
a substrate subsystem. Built.

### What it is

`core/guardian/supervisor.py` + `torin-guardian` — a separate process that
constructs and RUNS the monitoring and security systems, owns their control
loop, and is meant to start before the substrate and outlive it. The thing that
protects a system must be more durable than the thing it protects.

Hosts five real systems, each through its own module accessor: `health_monitor`,
`monitoring_coordinator`, `system_watchdog`, `security_audit_worker`,
`threat_blocking`. No system is reimplemented; the guardian hosts the real ones.

### Why it works without rewriting them

Confirmed earlier: each constructs standalone and touches the coordinator only
through optional guarded callbacks. Their one real coupling -- security findings
becoming remediation tasks -- already crosses the boundary through the task
queue (`TaskSource.SECURITY_AUDIT`), a row the substrate drains when it is up.

### No double ownership

When the guardian runs it is the sole authority for these systems' status and
control -- it holds the live objects. It writes a heartbeat
(`__guardian_heartbeat__`) each loop; the substrate's own control loop now calls
`guardian_present()` and DEFERS when a fresh heartbeat exists, so two processes
never drain one command queue. A crashed guardian releases ownership back to the
substrate fallback on its own, by the heartbeat going stale.

### Always-on

`config/org.dominionlabs.torin.guardian.plist` + `torin-guardian-install` — a
launchd agent with `RunAtLoad` and `KeepAlive`, so the guardian starts at boot
and relaunches if it ever exits. That is what makes "daemon" real rather than "a
script someone ran". Run `./torin-guardian-install` once.

### Verified against the real system

- guardian process launches and stays alive
- builds and STARTS all five systems standalone: 5 running, substrate not
  involved
- a dashboard `stop health_monitor` command, applied by the running guardian:
  running -> stopped
- heartbeat written and fresh (age 1s); `guardian_present` reads it
- launchd plist lints OK

Startup is ~9s (the guardian imports the substrate stack once); a one-time
daemon cost, not per-request.

### Two pre-existing bugs in the hosted systems, surfaced by running them

Not the guardian, and not fixed here -- recorded so they are not rediscovered:

- `threat_blocking` initialises the firewall and logs "Not running as root!
  Firewall operations may fail" -- it needs elevated privileges or a test mode.
- a monitoring loop raises `'str' object has no attribute 'metadata'` -- a real
  defect in the monitoring path.

### What this changes for the dashboard

Once the guardian runs (install it, or launch `./torin-guardian`), the
Monitoring and Security tabs' Start/Stop/Restart work whether the substrate is up
or down -- because the objects live in the guardian, and the guardian is always
on. The tabs already read the same `system_control_status` table; nothing in the
UI changes.

---

### Defect 38 — the tabs went blank when nothing was publishing — FIXED 2026-08-25

"no systems reported" whenever the status table was empty -- which is any time
neither the guardian nor the substrate had run since the table was created or
cleared. The tabs showed only PUBLISHED status, so a cold start looked broken.

The system list is static -- it is the registry -- so the tabs can always show
the eight systems and their off state. `torin-systems --status` now falls back
to the registry, marked `absent`, when the status table is empty; live status
overrides it the moment anything publishes.

The catch was cost: the registry lives in `core.health.system_control`, and
importing it the normal way pulls in `core/__init__` -- the whole stack, 9.75s.
So it is loaded IN ISOLATION (SourceFileLoader, registered in `sys.modules` so
its frozen dataclass resolves), the same trick torin-dash uses for channels.py.
Its module-level imports are stdlib only, so this stays at 0.10s.

Verified: nothing running -> all 8 listed absent (0.10s); guardian running -> 5
flip to running; guardian stopped -> still all 8, never blank.

Also confirmed the logs were never broken -- `torin-feed` returns all four
channels populated (substrate/system/security/health). The blank the report
referred to was the Monitoring tab's empty status table, now fixed.

---

### Logs blank in the app — a stale build, not a data fault (2026-08-25)

The Logs panes were empty while `torin-feed --json` returned all four channels
populated from the CLI (substrate 30, system 2095, security 322, health 130,
all fresh). Data path fine; the app binary was stale.

The app was built 13:37, the same minute as the final `Channels.swift` change, so
it predated the channel realignment -- its enum still had `tasks`, a channel the
feed no longer emits, while the new `health` channel it did not know about. A
clean rebuild (14:17) matches the source; relaunching the app picks it up.

Confirmed the four channel log files all carry recent content, including a
`health.log` being written live by the guardian's `health_monitor` -- visible
proof the always-on daemon runs and logs independent of the substrate.

Lesson for next time: a same-minute build/edit timestamp is not proof the build
included the edit. Rebuild after the last source change, not alongside it.

---

---

## What to do next, in order

1. **Promote a verified lexicon** into `data/lexicon.json`. EDU-16 already
   produced 1,326 confirmed words; nothing reads them. Smallest change, largest
   effect — the reader is waiting on it.
2. **Fix answering** (defect 5). Reading works, speaking works, and the middle
   step does not consult what was stored.
3. **Give the conversation faculty one state** (defect 7). A held instance, or
   an accessor keyed by session. Without it, continuity cannot be tested at all
   and several features in `conversation.py` are unreachable by construction.
4. **Make `InjectedMemories` carry records.** Its one real consumer is the
   substrate, which needs `Fact`s. **This is mechanical, not a design
   question** — see below.
5. **Wire `cached_memories`** (defect 3) — one line, removes the double fetch.
6. **Fix the coordinator's field name** (defect 1) — one line.
7. **Correct the stale headers** (defect 8), starting with `unified_llm.py`.
8. **Bind the executable operators at startup** (defect 10). The whole internal
   substrate path is live and correct up to its last stage; it refuses for want
   of a tool to act with. Nothing else on this list unblocks execution.

All of these are mechanical. An earlier draft of this document called item 4 a
design decision — *"what proposition, if any, does an episode contribute?"* —
and that was wrong. See **The substrate already has facts** below.

---

## The substrate already has facts

An earlier draft asked what proposition an episode contributes, as though it
were open. It is not. **The substrate produces evidence by acting**, and has
since `training_example_from_runtime` was wired.

`general_purpose_executor` reads the world before acting, acts, reads after, and
submits a real `TrainingExample(before, action, after, positive)` — the
before/action/after triple induction needs. Its own record of why:

> *"Until it was wired, the learner could only generalize from demonstrations a
> TEACHER supplied, and every concept a projected rule contributed was confined
> to a taught domain — which is why cross-domain transfer had exactly one source
> domain to draw on."*

The discipline is already correct. No demonstration is recorded when the world
could not be read afterwards (*"an unobserved after-state is not an empty
one"*), none for an INDETERMINATE outcome (*"an unlabelled example would be
induced from as a positive"*), and none without a domain (*"inventing a domain
here is how one topic acquired 21"*).

**69 evidence roots back the 12 rules**, of five kinds:

    induction_negative      supports=False   26    the counterexamples
    induction_positive      supports=True    23
    validation_positive     supports=True    15
    runtime_confirmation    supports=True     4    from acting
    runtime_contradiction   supports=False    1    the world said no

More negatives than positives, which is the right shape: a counterexample is
what refutes an overgeneral rule. And `runtime_*` roots — `e2e_obs_f1ebc7b0…`,
`edu02_1787151946` — are evidence the substrate produced by doing something,
not by being told. The second is the observation that refuted the broad MOVE
rule when the filesystem refused it.

So memory does not need a new fact-extraction design. What defect 2 needs is for
`InjectedMemories` to stop discarding the structured rows retrieval already
found.

---

## Why this document exists

The system is being moved from **model-at-the-centre** to **substrate-first**,
and the two arrangements are still tangled together. The defects above are not
scattered mistakes — they are the seam:

- memory shaped as a **prompt** (2) because a model used to be its only reader
- a coordinator field name from a **different shape** of the same object (1)
- a wire designed for the substrate and never connected (3)
- a language faculty whose **state** is discarded because callers construct it
  ad hoc (7)
- headers describing the **old** architecture (8)

Every one is a place where something was rebuilt underneath and its callers were
not moved. Expect more of them, and expect them to look like absence: a `None`,
an empty result, a component that reports nothing found. That is what a severed
connection looks like from the outside, and it is why every claim in this
document carries the measurement that produced it.
