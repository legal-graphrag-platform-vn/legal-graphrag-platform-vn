# LuatVietnam crawler experiment

This folder is deliberately isolated from `src/pipeline` and `data/raw`. It is
for evaluating `luatvietnam.vn` as a new source before any curated-ingestion
decision is made.

## Install and test

From the repository root:

```bash
uv sync --group dev
uv run playwright install chromium
uv run pytest -q experiments/luatvietnam_crawler/tests
```

## Run a full crawl from scratch

Run every command from the repository root. Put the complete LuatVietnam search
URL in a shell variable so `&` characters are not interpreted by the shell:

```bash
cd ~/Projects/graph-RAG

LUATVN_SEARCH_URL='<paste the complete LuatVietnam search URL here>'
```

First, load every search-result page into one discovery manifest. Omit
`--max-pages` and `--max-documents` so the crawler uses the site total and
selected `PageSize` to calculate the full page range:

```bash
uv run python -m experiments.luatvietnam_crawler list \
  --url "$LUATVN_SEARCH_URL" \
  --output experiments/luatvietnam_crawler/output/lists/discovery.json \
  --request-budget 40 \
  --daily-request-budget 100
```

Split the discovery manifest into resumable detail jobs:

```bash
uv run python -m experiments.luatvietnam_crawler prepare-jobs \
  --discovery experiments/luatvietnam_crawler/output/lists/discovery.json \
  --output-root experiments/luatvietnam_crawler/output/jobs
```

The command prints the generated `bundle_dir`. Copy that path into
`LUATVN_BUNDLE`, for example:

```bash
LUATVN_BUNDLE='experiments/luatvietnam_crawler/output/jobs/search-b8815dbc1ba4bc3a'
```

Crawl detail pages in bounded batches. Run this command again to resume from the
next pending job:

```bash
uv run python -m experiments.luatvietnam_crawler crawl-jobs \
  --bundle "$LUATVN_BUNDLE" \
  --max-jobs 20 \
  --request-budget 20 \
  --daily-request-budget 100
```

Inspect aggregate progress at any time:

```bash
uv run python -m experiments.luatvietnam_crawler job-status \
  --bundle "$LUATVN_BUNDLE"
```

Completed documents are written under `output/raw/LTV_<id>/` with
`metadata.json`, canonical `source.txt`, and the retained browser DOM snapshot
`source.html`. Documents marked `Trạng thái: Chưa thông qua` are terminal
`skipped` metadata-only records and intentionally have no text or HTML artifact.
Do not raise `--daily-request-budget` to bypass an exhausted safety state; wait
for its UTC-day reset and resume the same bundle.

## Crawl

Keep the full search URL quoted because it contains `&` characters:

To create only a JSON list of detail URLs (no detail-page requests):

```bash
uv run python -m experiments.luatvietnam_crawler list \
  --url 'https://luatvietnam.vn/van-ban/tim-van-ban.html?...&PageSize=100&PageIndex=1' \
  --output experiments/luatvietnam_crawler/output/lists/discovery.json
```

The list uses schema `luatvietnam-discovery-v3` and reads only
`article.art-search` result cards, preserving result rank, source page,
LuatVietnam external ID, title, canonical detail URL, detail variant, and source
kind. Supported variants are issued documents (`d1`), consolidated documents
(`d5`), and drafts (`d10`). Drafts are explicitly labelled and must not be
treated as issued normative documents.

By default, `list` reads the result summary (`Có 3.353 văn bản`), the selected
page-size option, active page, and pagination links. It calculates page count as
`(total_results + page_size - 1) // page_size`; for example, 3,353 results at
100 per page produce 34 pages. Subsequent URLs normalize `PageSize`, `PagSize`,
and `PageIndex` to the values shown by the site. `--max-pages` and
`--max-documents` are optional safety caps; omitting both lists every search
result without opening detail pages. The manifest includes the raw filter
summary plus parsed document types, fields, language, and an exact raw issuer
string. Issuers are not split on commas because valid names such as
`Bộ Văn hóa, Thể thao và Du lịch` contain commas.

The manifest keeps unique detail URLs in `documents` while separately auditing
page-boundary overlap through `result_occurrence_count`,
`duplicate_occurrence_count`, and `duplicate_occurrences`. Therefore a site
total of 3,353 card occurrences can correctly correspond to 3,352 unique detail
URLs without silently losing the repeated page occurrence.

## Resumable detail-job bundle

After `list` has loaded every search page, split that immutable discovery file
into small, durable detail jobs without making any additional web request:

```bash
uv run python -m experiments.luatvietnam_crawler prepare-jobs \
  --discovery experiments/luatvietnam_crawler/output/lists/discovery.json \
  --output-root experiments/luatvietnam_crawler/output/jobs
```

The output folder is deterministic for the full search URL, so preparing the
same search again updates its index while preserving completed job states:

```text
output/jobs/search-<url-hash>/
├── manifest.json               # ordered master job list
├── state.json                  # counts and the next resumable job
├── pages/
│   ├── page-0001.json          # jobs discovered on search page 1
│   └── ...
└── jobs/
    ├── LTV_<id>-d1.json        # one independently stateful detail job
    └── ...
```

Each job starts as `pending`. A worker claims the next `pending` job (or a
`retryable` job after all pending work), then records its result:

```bash
uv run python -m experiments.luatvietnam_crawler job-status \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash>

uv run python -m experiments.luatvietnam_crawler job-next \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash> \
  --claim

uv run python -m experiments.luatvietnam_crawler job-update \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash> \
  --job-id LTV_<id>-d1 \
  --status completed \
  --output-directory experiments/luatvietnam_crawler/output/raw/LTV_<id>
```

Supported states are `pending`, `in_progress`, `completed`,
`content_unavailable`, `skipped`, `retryable`, and `failed`. Claims and updates use a
process lock; all JSON writes are atomic.
An interrupted `in_progress` job is reported separately in `state.json` instead
of being silently claimed a second time. An operator can explicitly return it
to `retryable` after checking that no worker still owns it.

Run the detail worker in bounded batches; it resumes from `state.json` and does
not request the search-result pages again:

```bash
uv run python -m experiments.luatvietnam_crawler crawl-jobs \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash> \
  --max-jobs 20 \
  --request-budget 20 \
  --daily-request-budget 100
```

Successful jobs become `completed`; transient failures become `retryable`, and
reach `failed` after `--max-attempts`. A job is attempted at most once in one
worker run. HTTP 403/429/challenge handling still stops immediately and returns
the claimed job to `retryable` before exiting.

The worker prints one compact start line, one fetch/result line per job, and one
final state line before its JSON report. Pass `--quiet` to suppress these
progress lines while retaining the final JSON output.

Canonical `source.txt` is serialized from the legal-content DOM rather than
flattening all page text. UI controls and tooltips are removed, block-level legal
structure is preserved, and only `span.noi-dung-tham-chieu` is marked as
`[reference text]`. Ordinary formatting spans and `a.doclink` links remain plain
text. The exact browser response DOM is also stored atomically as `source.html`
so later parser experiments do not require another site request. Metadata records
serializer version `luatvietnam-detail-v2`, character and Article counts, the
number of reference markers, and whether raw HTML was saved.

Documents whose detail metadata says `Trạng thái: Chưa thông qua` are retained
as metadata-only records with `skip_reason=not_approved`; their jobs finish as
`skipped` and neither `source.txt` nor `source.html` is created.

If LuatVietnam explicitly says that HTML full text is not published, the worker
saves the available detail metadata under `output/metadata-only/LTV_<id>/`, sets
the terminal state `content_unavailable`, and continues. It does not create an
empty `source.txt`, but it does retain the fetched page as `source.html`. It does
not consume the failure budget, retry the job, or make the CLI exit with code 2.
To migrate job bundles produced by the earlier behavior:

```bash
uv run python -m experiments.luatvietnam_crawler migrate-job-states \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash>
```

The migration is idempotent and only reclassifies `retryable`/`failed` jobs
whose recorded error starts with `ContentUnavailableError:`. It does not fetch
the site; metadata-only output is created on new crawl attempts only.

Completed jobs from an older content serializer, or without retained raw HTML,
can be inspected and explicitly returned to `pending`. The default is read-only;
add `--apply` to update jobs:

```bash
uv run python -m experiments.luatvietnam_crawler requeue-stale-content \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash>

uv run python -m experiments.luatvietnam_crawler requeue-stale-content \
  --bundle experiments/luatvietnam_crawler/output/jobs/search-<url-hash> \
  --apply
```

To enrich each list row with metadata from its detail page:

```bash
uv run python -m experiments.luatvietnam_crawler metadata-list \
  --url 'https://luatvietnam.vn/van-ban/tim-van-ban.html?...&PageSize=100&PageIndex=1' \
  --max-pages 1 \
  --max-documents 5 \
  --output experiments/luatvietnam_crawler/output/lists/metadata-list.json
```

Schema `luatvietnam-metadata-list-v3` adds the original document type, issuer,
signer, abstract, issue/application/expiry dates (plus their raw values), legal
status, gazette metadata, fields, page-update timestamp, Open Graph metadata,
and HTML full-text availability/counts. Unknown gated values such as `Đã biết`
or `Đang cập nhật` are retained as raw values but are not guessed as dates or
legal status. Unlike `list`, this command opens one detail page per document.

To open each discovered detail page and save raw text:

```bash
uv run python -m experiments.luatvietnam_crawler crawl \
  --url 'https://luatvietnam.vn/van-ban/tim-van-ban.html?...&PageSize=100&PageIndex=1' \
  --max-pages 1 \
  --max-documents 20 \
  --min-request-delay 7 \
  --max-request-delay 12 \
  --request-budget 25 \
  --daily-request-budget 100
```

Default output stays inside this experiment:

```text
experiments/luatvietnam_crawler/output/
├── last_run.json
└── raw/
    └── LTV_<luatvietnam-id>/
        ├── metadata.json
        ├── source.txt
        └── source.html
```

Use `--headed` if Cloudflare requires a visible browser. The command exits with
code `2` if any detail page fails, while `last_run.json` records all failures.
Existing documents are skipped unless `--overwrite` is passed.

The default runtime launches the system-installed Google Chrome (`channel="chrome"`)
with a visible, maximized window and a persistent profile. Pass `--headless` only
for CI. The crawler does not override Chrome's User-Agent or browser fingerprint.

## Anti-block safety

- The default persistent Chrome profile is stored in `runtime/chromium-profile`.
  Reuse it between runs so cookies and the browser identity remain stable.
- Keep one stable outbound IP. This experiment intentionally has no proxy rotation,
  fingerprint spoofing, or automatic challenge bypass.
- Every browser request is paced by a random 7-12 second delay. Start with one page
  and a small document limit; increase only after reviewing `last_run.json`.
- HTTP 403, HTTP 429, and visible Cloudflare/challenge pages stop the run immediately.
  Do not loop or restart repeatedly after a block.
- `runtime/safety-state.json` persists the last request, daily quota, and cooldown
  across process restarts. A block signal activates a 24-hour cooldown by default;
  a longer server `Retry-After` value wins.
- `runtime/crawler.lock` prevents two crawler processes from sharing the same
  browser profile concurrently. Defaults cap traffic at 25 requests per run and
  100 requests per UTC day. Three detail failures stop the run early.
- Review LuatVietnam's current terms and robots policy before a larger collection.

The emitted `candidate_graph_id` is only a promotion hint. Experimental output
must not be copied into canonical `data/raw` until its metadata and identity are
reviewed and added to the curated corpus contract.
