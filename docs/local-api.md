# Local HTTP API

Use the optional HTTP service to inspect strategy source, save drafts, import datasets, and submit saved revisions for backtesting. To use these workflows in a browser, start the [local browser workspace](browser.md).

## Start the service

From the repository root, install the optional API dependencies and start the supervisor with a fresh library. The examples use a POSIX shell and `curl`.

```sh
uv tool install --python 3.12 '.[api]'
library_root=$(mktemp -d "${TMPDIR:-/tmp}/tradelang-library.XXXXXX")
tradelang-local --data-root "$library_root"
```

In another terminal, check the service and inspect the generated OpenAPI schema.

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/openapi.json
```

The default API address is `127.0.0.1:8000`. When you start `tradelang-local` with `--api-port` or `--web-port`, use the configured API port in the request address and the configured browser port in the Origin header. With the defaults, send `Origin: http://127.0.0.1:3000` for POST, PUT, and DELETE. Use `Content-Type: application/json` for JSON writes and multipart for dataset uploads. Use Ctrl-C in the service terminal to stop it.

For source-only inspection, start `tradelang-api` on the same port after stopping the supervisor. The standalone service has the two editor endpoints and reports degraded health because it runs without a worker. The supervisor persists drafts, datasets, and backtests under `--data-root`. Health reports the number of queued jobs. If the worker stops, `/health` returns HTTP 503 while editor routes remain available.

## Validate or explain source

Both routes accept a JSON object containing `source` and an optional `dataset_id`. For a strategy using `VPROFILE`, send the primary `dataset_id` and a separate `profile_dataset_id` for the [lower-timeframe input](candle-data.md#pair-candles-for-volume-profile). An unknown supplied ID returns HTTP 404 with `E_DATASET_NOT_FOUND`. An incompatible pairing returns HTTP 200 with `valid: false` and an `E402_WINDOW` diagnostic. Start with a source-only request in the second terminal, from the repository root.

```sh
api=http://127.0.0.1:8000/api/v1
payload=$(uv run --no-project --python 3.12 python -c 'import json, pathlib; print(json.dumps({"source": pathlib.Path("docs/fixtures/core.trade").read_bytes().decode("utf-8")}))')
curl -fsS "$api/strategies/validate" \
  -H 'Origin: http://127.0.0.1:3000' -H 'Content-Type: application/json' \
  --data-binary "$payload"
```

Use the same body with `/api/v1/strategies/explain`. Both responses carry `valid`, diagnostics, and the source hash. A compiled source has a spec hash and warmup index. Validation gives the typed `spec` on success. Explanation gives `text` and `assumptions`. A source-only request leaves `resolved_window` null and, on the validation response, `data_compatible` null.

For [DSL 3 named feeds](language-v3.md), send `feed_ids` with the primary `dataset_id` during inspection and submission. The object maps the declared feed name to a dataset UUID. Source-only validation returns the reachable names in `spec.required_feeds`. An accepted run records the feed identities and alignment policies in `configuration.feeds`.

The typed spec uses `null` for `symbol` and `timeframe_seconds` when the source omits those declarations. With a `dataset_id`, the selected dataset supplies the effective symbol and duration. The explanation displays those values, and the spec hash stays the same across dataset selections.

For [DSL 2 source](language-v2.md), optionally send `"parameters": {"fast": 1}` with either request. Use JSON numbers or Booleans in the declared types and units. Each name can appear once in a JSON object. The DSL 2 typed spec includes the defaults and effective values and reports `requires_profile` for reachable Volume Profile calls.

For [DSL 4 stop-based sizing](language-v4.md), `spec.entry.sizing.kind` is `stop_risk`. The spec includes the risk expression and a typed `allocation_cap` expression when supplied. On a buy fill, `GET /api/v1/backtests/{ident}/bars/{index}` includes the recorded `risk_sizing` evidence and the binding constraint.

For [DSL 5 ordered exits](language-v5.md), `spec.exit.rules` lists the conditions or holding counts in source order. The candle inspection response includes `holding_closes` and per-rule outcomes at evaluated closes. `trail_updates` includes queued and activated stop levels, and `trail_expression` shows samples for the trailing distance at an evaluated close while holding.

For [DSL 6 quantity management](language-v6.md), the exit action describes the sale kind and its quantity expression. The typed spec includes optional `scale` and `risk.quantity_step` settings. Filter `GET /api/v1/backtests/{ident}/events` by `kind=fill` and `trade_id` for a position's fill history. Each quantity-managed fill has a typed `ledger` field.

A successful dataset-aware inspection includes `workload`. Submission uses the same preflight and stores the estimate with the run. If required resident arrays exceed the memory budget, the inspection reports `E_DATA_LIMIT` and submission returns HTTP 422 without queueing a run. [Workload fields](results.md#review-workload)

### Check a draft

Send `{"source": "..."}` to `POST /api/v1/strategies/draft-check` for source-only editor assistance. The response includes the exact `source_hash` and up to eight independent errors. Recovery can check later declarations and sections after a syntax error when they start on separate lines. A failed declaration can prevent checking expressions that depend on it.

On failure, `valid` is false and `spec` is null. The `records` array can still include fields and scale metadata from valid record declarations. When a diagnostic offers an exact edit, its `details` contains `original` and `replacement`. Check the source hash and original bytes at the diagnostic span before applying the replacement. Use the full validation route for the selected run inputs.

## Save a draft and import candles

### Import and select a dataset

With the supervised service running, upload the [quickstart candles](fixtures/core.csv) and [metadata](fixtures/metadata.json). The first import into the fresh library returns HTTP 201 with `deduplicated: false`. Use the returned `dataset.id` in inspection requests.

```sh
imported=$(curl -fsS "$api/datasets/import" \
  -H 'Origin: http://127.0.0.1:3000' \
  -F 'file=@docs/fixtures/core.csv' -F 'metadata=<docs/fixtures/metadata.json')
dataset_id=$(printf '%s\n' "$imported" | uv run --no-project --python 3.12 python -c 'import json, sys; print(json.load(sys.stdin)["dataset"]["id"])')
```

Dataset IDs select individual imports. Use `dataset_hash` to compare normalized candles and semantic metadata across imports. Equivalent CSV and Parquet uploads can also have distinct IDs and share a hash.

For [exchange sessions](language-v7.md), send schema 2 JSON in the metadata part. The import can carry up to 2 MiB of metadata with the candle file. The dataset fingerprint includes the recorded calendar and supplied split actions.

| Upload after the first import | HTTP status | Identity |
| --- | --- | --- |
| Same file bytes and validated metadata, with the upload filename changed to `renamed.csv` | 200 | `deduplicated: true`, original `dataset.id` and `dataset_hash`. |
| Same file bytes with `timeframe` changed from `1d` to `24h` in the metadata | 201 | `deduplicated: false`, new `dataset.id` and the same `dataset_hash`. Both timeframes normalize to the same duration. |

### Validate and explain with the dataset

Add the imported ID to the source-only `payload` from the previous section and send the resulting body to both routes.

```sh
with_dataset=$(printf '%s\n' "$payload" | uv run --no-project --python 3.12 python -c 'import json, sys; print(json.dumps(dict(json.load(sys.stdin), dataset_id=sys.argv[1])))' "$dataset_id")
for command in validate explain; do
  curl -fsS "$api/strategies/$command" \
    -H 'Origin: http://127.0.0.1:3000' -H 'Content-Type: application/json' \
    --data-binary "$with_dataset"
  printf '\n'
done
```

Both responses have `valid: true` and the following `resolved_window`. The validation response also has `data_compatible: true`.

```json
{
  "first_open": "2024-01-01T00:00:00Z",
  "last_close_at": "2024-01-04T00:00:00Z",
  "readiness_index": 0,
  "first_signal_at": "2024-01-02T00:00:00Z",
  "first_execution_at": "2024-01-02T00:00:00Z"
}
```

`readiness_index` is the zero-based [structural warmup index](language-spec.md#unavailable-and-bounded-computation). Here the first eligible close and next open share a timestamp because the candles are contiguous.

Check `valid` even on HTTP 200. For example, changing the strategy market to `OTHERUSDT` yields `valid: false`, a null `resolved_window`, and an `E402_WINDOW` diagnostic. On validation, `data_compatible` is `false` in this case. A well-formed UUID absent from the library returns HTTP 404 with `E_DATASET_NOT_FOUND` in the [error response](#handle-errors).

### Save and update a draft

```sh
draft=$(printf '%s\n' "$payload" | uv run --no-project --python 3.12 python -c 'import json, sys; print(json.dumps(dict(json.load(sys.stdin), name="Golden demo")))')
curl -fsS -i "$api/strategies" \
  -H 'Origin: http://127.0.0.1:3000' -H 'Content-Type: application/json' \
  --data-binary "$draft"
```

Drafts can contain work-in-progress source. Creation returns HTTP 201, a `Location` header, an `ETag` header, and `current_revision: 1`. Pass the current ETag as `If-Match`, including its quotes, and the current revision as `expected_revision` when updating the draft. A source change creates a new revision and ETag. A rename changes the ETag and preserves the revision number. An identical update preserves both.

Archiving with `DELETE` and the current ETag returns HTTP 204. The draft disappears from the active list and its detail route returns HTTP 404. Its revision list and saved revisions remain readable.

## Submit and compare backtests

Submit a JSON object to `POST /api/v1/backtests` with `strategy_id`, `strategy_revision`, and `dataset_id`. Use the current saved revision, the import's gap policy, and a `profile_dataset_id` when running a strategy that requires Volume Profile. When the selected primary dataset allows gaps, send `"policy": {"gap_policy": "allow"}` explicitly. Send an `Idempotency-Key` UUID to retry the same request safely within 24 hours.

The API responds with HTTP 202 and a run ID. Poll its `Location` until the run succeeds, fails, or is cancelled. If you update the strategy after submission, the run still uses the source and dataset it recorded at submission. After a success, retrieve full or sampled equity, page through trades and events, or download an artifact. Compare two to four succeeded runs by passing comma-separated IDs in the `ids` query parameter.

For a DSL 8 short, `configuration.short_margin` records the simulation terms. `summary.short_accounting` reports restricted proceeds, initial margin, reserved and available cash, liquidation count, and insolvency status. Equity points and fill ledgers use signed remaining quantity. Trades report positive filled quantity with `direction: "short"`. [Short order and accounting rules](language-v8.md)

The comparison response includes `common_benchmark`. Its `cohorts` array contains each eligible group, its common window and costs, rebased strategy returns, and up to 1,000 chart points per group. Its `pairs` array reports a reason for each ineligible pair. [Common-start policy](results.md#compare-a-common-start-benchmark)

Send the same `parameters` object as in validation to override DSL 2 defaults. Submission returns HTTP 422 for invalid overrides. An accepted run snapshots the effective parameters, which you can read in `configuration.parameters`.

### Apply and save run settings

For validation, explanation, and submission, optionally send a `settings` object with `from_date`, `to_date`, `capital`, `fee_bps`, `slippage_bps`, `gap_policy`, or `parameters`. Dates are inclusive UTC dates. Values resolve from source defaults, then the selected preset, then explicit overrides. Top-level `parameters` override matching names in `settings.parameters`.

Create a reusable preset at `POST /api/v1/run-presets` with `name`, `settings`, and optional `dataset_id` and `profile_dataset_id`. Pass the returned ID and revision as `preset_id` and `preset_revision` when inspecting or submitting. You can omit a dataset field to use its preset value. An explicit null clears that selection. Update a preset with `PUT /api/v1/run-presets/{id}`, the replacement fields, and `expected_revision`. A stale revision returns HTTP 409 with `E_PRESET_CONFLICT`.

Check `run_configuration` in a successful inspection for the effective dates, costs, capital, dataset hashes, and parameters. Its `origins` records where each override or default came from. An accepted run records the same payload in `configuration.effective`.

## Inspect a candle

Use `GET /backtests/{id}/bars/{index}` under `/api/v1` for a succeeded run. Pass the zero-based primary dataset `bar_index` from an equity row. The response reports whether each rule was evaluated, its predicate and outcome, and linked events. Expression samples include the typed node ID, source span, sample bar and time, and value or unavailable reason. Crossings include both operands on both observed bars. Fill evidence identifies the originating signal bar and the cash and sizing used at the open.

Read `available` and `reason` to check sample availability. Bundles made before decision recording report `inspection_not_recorded`. The endpoint can return saved outcomes and events with `inspection_runtime_mismatch`, `inspection_work_limit`, or `inspection_busy` when expression samples cannot be rebuilt. An index outside a recorded execution window returns HTTP 422 with `E_RANGE`.

## Routes

The running service's [OpenAPI document](http://127.0.0.1:8000/openapi.json) describes the request and response schemas. Paths in the table are relative to `/api/v1`.

| Method and path | Behavior |
| --- | --- |
| `POST /strategies/validate` | Compile source and optionally validate window compatibility. |
| `POST /strategies/explain` | Explain the compiled source and assumptions. |
| `POST /strategies/draft-check` | Recover independent draft errors, fixes, and record fields. |
| `GET /run-presets`, `POST /run-presets` | List or create reusable run presets. |
| `GET /run-presets/{id}`, `PUT /run-presets/{id}` | Read or replace a preset at a specific revision. |
| `GET /strategies`, `POST /strategies` | List active drafts or save a new draft. The optional `q` query parameter matches substrings of the draft name, case-insensitively. |
| `GET /strategies/{id}` | Read the current draft and ETag. |
| `PUT /strategies/{id}` | Send `name`, `source`, and `expected_revision` with the current `If-Match` ETag. |
| `DELETE /strategies/{id}` | Archive the draft with the current `If-Match` ETag. |
| `GET /strategies/{id}/revisions`, `GET /strategies/{id}/revisions/{revision}` | List or read saved source revisions. |
| `GET /datasets`, `GET /datasets/{id}` | List imports or read metadata, quality, and a row preview. |
| `POST /datasets/import` | Upload one `file` and one `metadata` JSON part. |
| `GET /backtests`, `POST /backtests` | List runs or submit a saved revision. |
| `GET /backtests/{id}`, `POST /backtests/{id}/cancel` | Read a run or request cancellation with an empty JSON object. |
| `GET /backtests/{id}/equity` | Read a full page or a bounded envelope of equity rows. |
| `GET /backtests/{id}/trades`, `GET /backtests/{id}/events` | Page through closed trades or linked audit events. |
| `GET /backtests/{id}/bars/{index}` | Inspect the rule outcomes, expression samples, and events for one observed candle. |
| `GET /backtests/{id}/artifacts/{name}` | Download allowlisted result artifacts. |
| `GET /backtests/compare` | Read full-run metrics and align curves for two to four succeeded runs. |

Library routes require the supervised service. List routes accept `limit` from 1 to 500 (default 50). They return `items`, `next_cursor`, and `snapshot`, the creation-time cutoff used for pagination. Pass `next_cursor` as an opaque `cursor` on the same list route and with the same filters. A null `next_cursor` marks the last page.

## Handle errors

For non-success HTTP responses from inspection and library routes, read `error.code` and `error.message`. The JSON response also includes `schema_version: 1`, a `request_id`, and `error.diagnostics` and `error.retryable`. Dataset validation failures may include row diagnostics. To see the status, headers, and error body in `curl`, use `-i` and omit `-f`. For inspection responses with HTTP 200, read the top-level `valid` and `diagnostics` fields.

| HTTP status | What to check |
| --- | --- |
| 400 | Fix malformed JSON or multipart data. An invalid cursor or a cursor used with different filters also returns 400. |
| 403 | Verify the loopback address and the required `Origin` on writes. |
| 404 | Check the resource ID. Inspection with an unknown dataset ID returns `E_DATASET_NOT_FOUND`. |
| 409 | The ETag or revision is stale. Read the draft again before retrying the update or archive. |
| 413, 415, 422 | Check size limits, media type, or request fields. Strategy source is capped at 64 KiB of UTF-8 and JSON requests at 128 KiB. For candle file limits, see [Candle data](candle-data.md#file-formats). |
| 428 | Send the required `If-Match` header when updating or archiving a draft. |
| 429 | The editor is rate-limited or the import capacity is full. Wait the number of seconds in the `Retry-After` header before retrying. |
