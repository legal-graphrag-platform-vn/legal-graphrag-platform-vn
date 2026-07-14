# Legal GraphRAG Frontend

Next.js pilot interface for chat, grounded citations, document exploration, and
graph visualization. The frontend consumes the FastAPI contracts under
`/api/v1`; it does not access Neo4j or model providers directly.

## Run

Start the backend first. For the disposable pilot database, ensure the backend
uses `NEO4J_URI=bolt://localhost:7688` after dotenv loading.

```bash
cd apps/frontend
npm ci
npm run dev
```

The client reads:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Open `http://localhost:3000`.

## Verify

```bash
npm test
npm run lint
npm run format:check
npm run build
```

## Current Status

```text
Frontend scope: pilot development
Current legal corpus: L59_2020 pilot
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```

The UI must not present pilot metrics as production accuracy, latency, corpus
coverage, pricing, quota, or SLA evidence.
