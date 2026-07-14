# Answer Generation Development Evidence

Generated: 2026-07-14

```text
plan = plans/agent-plan-feats/11_phase2_answer_generation_plan.md
base_commit = 21506ef1be496a242b400c7312a00e18aa398dd8
working_tree_state = dirty (implementation worktree, not official evidence)
answer_generation = implemented
backend_chat_integration = implemented
real_provider_smoke = pass
pilot_answer_evaluation = technical_pass_human_review_pending
Gate 7 / M3-B13 = OPEN
Milestone A = NOT PASSED
Milestone B acceptance = NOT STARTED
```

## Runtime Contract

- Answer generation consumes the original `RetrievalContext`; it does not
  reverse-map the public query response.
- Unsupported retrieval failures propagate and insufficient/no-result contexts
  return deterministic `cannot_answer` responses without a provider call.
- The model returns structured claims, citation IDs, trusted path IDs, and
  temporal assertions.
- Trusted code validates and renders citations, graph explanations, temporal
  notes, deep links, and final SSE events.
- Answer tokens are emitted only after the complete candidate passes grounding.
- `ANSWER_GENERATION_ENABLED=false` keeps GraphRAG retrieval-only and constructs
  no provider resource.

## Provider Contract

```text
provider = gemini
default model = gemini-3.5-flash
structured output = AnswerCandidate
timeout = includes limiter wait, retries, and provider call
retry = transient rate-limit/server failures only
fallback = disabled
```

The opt-in live provider smoke passed with `google-genai==2.11.0` and
`gemini-3.5-flash`. The earlier `gemini-2.5-flash` default was rejected by the
provider as unavailable for new users. Enabling the profile requires the `llm`
dependency group and a runtime `GEMINI_API_KEY`.

## Verification

```text
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q
348 passed, 8 deselected

RUN_NEO4J_INTEGRATION=1 NEO4J_URI=bolt://localhost:7688 \
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest \
tests/integration/test_retrieval_online.py -q -m retrieval_readonly
2 passed

ruff check changed Python scope
PASS

RUN_ANSWER_PROVIDER_INTEGRATION=1 \
UV_CACHE_DIR=/tmp/uv-cache uv run dotenv run -- pytest \
tests/provider/test_answer_provider_online.py -q -m answer_provider_live
1 passed
```

## Pilot Answer Evaluation

```text
source_commit = b9638f8
runtime = Neo4j disposable pilot on localhost:7688
dataset = configs/evaluation/answer_pilot_l59_2020_draft.json
report = results/answer_generation/answer_pilot_l59_2020_development.json
case_count = 8
hard_checks = PASS (8/8)
answered_cases = 5
unsupported_capability_cases = 3
human_legal_review = PENDING (8/8)
official_evidence_eligible = false
```

The first development attempt inherited port `7687` from `.env` and was
discarded. The retained report was regenerated with `NEO4J_URI` explicitly set
to the disposable pilot port after dotenv loading.

## Limitations

- The answer-quality dataset and generated answers require `lamdx4` legal
  review before promotion or official evaluation.
- SSE transport validates before streaming and therefore does not optimize
  first-token latency.
- Gate 7/four-document corpus and all milestone statuses remain unchanged.
