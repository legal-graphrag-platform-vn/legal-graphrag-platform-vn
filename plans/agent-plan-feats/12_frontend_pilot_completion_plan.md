# Frontend Pilot Completion Plan

## Status Contract

```text
Backend pilot implementation: IMPLEMENTED
Frontend pilot completion: COMPLETE FOR PILOT
End-to-end pilot acceptance: NOT PASSED
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```

This plan makes the existing Next.js client reliable against the implemented
backend contract. It does not claim production scale, SLA, corpus completeness,
or legal correctness beyond reviewed pilot evidence.

## Scope

1. Make ESLint, TypeScript, and production build pass without disabling rules.
2. Keep one typed SSE parser for `metadata`, `token`, `citation`, `error`, and
   `done` events.
3. Preserve canonical citation/deep-link fields from backend DTOs.
4. Make stream cleanup deterministic on success, error, abort, and unmount.
5. Keep document hooks race-safe and expose loading/error states consistently.
6. Add frontend unit/contract tests for parser, API errors, and deep links.
7. Replace unverified production metrics/pricing/SLA claims with pilot wording.
8. Replace the generated Next.js README with repository-specific run and
   verification instructions.

## Out Of Scope

- Authentication, billing, quotas, production deployment, and SLA.
- Gate 7 corpus expansion.
- Changing retrieval, generation, ontology, or Neo4j write behavior.
- Claiming Milestone A or B completion.

## Implementation Steps

### 1. State and lint cleanup

- Remove derived state where URL search params are already the source of truth.
- Use React transitions for effect-triggered state synchronization.
- Keep fetch cancellation guards and clear stale data when identity changes.
- Remove dead imports and resolve hook dependency warnings.

### 2. SSE contract module

- Extract line/event parsing from `useChatStream` into a pure typed module.
- Parse named backend events only; remove dead Flask compatibility behavior.
- Treat malformed JSON and unknown events as typed protocol errors.
- Consume citation events and preserve `deep_link`.
- Ensure one `done` event completes the stream and error always clears timers.

### 3. Frontend API contract

- Centralize API base URL usage.
- Preserve backend error status and safe message.
- Use canonical `query_date` in new requests.
- Keep source DTO mapping explicit and typed; no `any`.

### 4. Honest pilot UI

- Remove unsupported corpus size, latency, accuracy, pricing, quota, and SLA
  claims from the landing page.
- Label the product as a research/pilot interface over the current corpus.

### 5. Tests

- Add Vitest with jsdom only for frontend unit/contract tests.
- Test fragmented SSE chunks, Unicode, metadata, citations, done, error, malformed
  JSON, and unknown events.
- Test API non-2xx behavior and deterministic deep-link construction.
- Do not use the live Gemini provider or mutate Neo4j in frontend tests.

## Verification

```bash
cd apps/frontend
npm test
npm run lint
npm run build
npm run format:check

cd ../..
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest apps/backend/tests -q
git diff --check
```

## Acceptance

```text
FE-01 ESLint has zero errors.
FE-02 Production build succeeds.
FE-03 Frontend tests pass and cover SSE failure paths.
FE-04 Backend tests remain green.
FE-05 Citation deep links survive the SSE mapping boundary.
FE-06 No unreviewed production metrics or SLA claims remain.
FE-07 Gate and milestone statuses remain unchanged.
```

## Completion Status

```text
Plan status: IMPLEMENTED
Frontend implementation: COMPLETE FOR PILOT
Frontend verification: PASS
End-to-end pilot acceptance: NOT PASSED
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```
