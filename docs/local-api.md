# Local HTTP API

The optional local HTTP API validates and explains strategy source. In supervised mode, it also stores strategy drafts and imported datasets. Run simulations with the [CLI](cli.md#backtest).

## Start the service

Follow [Use the local HTTP API](use-local-api.md#start-the-service) to install the optional dependencies and start the service.

| Command | Available routes |
| --- | --- |
| `tradelang-local` | Health, OpenAPI, strategy inspection, and the draft and dataset library. The library persists under `--data-root`. |
| `tradelang-api` | Health, OpenAPI, and source inspection. |

Both modes listen on `127.0.0.1:8000` and require that address in the Host header. For POST, PUT, and DELETE, send `Origin: http://127.0.0.1:3000`. Send `Content-Type: application/json` for JSON bodies and multipart form data for dataset imports.

`GET /health` returns HTTP 200 with `status: "ok"` when the worker is available. Without a worker, including in standalone mode, it returns HTTP 503 with `status: "degraded"`. Inspection routes remain available while the API process is running.

## Validate or explain source

For runnable requests, see [Validate or explain source](use-local-api.md#validate-or-explain-source).

Both inspection endpoints accept `source` and an optional `dataset_id`. Responses include `valid`, diagnostics, and the source hash. A compiled strategy has a spec hash and warmup index. Successful validation returns the typed `spec`. Explanation returns `text` and `assumptions` for valid source and compatible data. A source-only request has `resolved_window: null` and, for validation, `data_compatible: null`.

## Save a draft and import candles

Follow the [supervised library workflow](use-local-api.md#save-a-draft-and-import-candles) to use these endpoints.

- <a id="import-and-select-a-dataset"></a>[Import and select a dataset](use-local-api.md#import-and-select-a-dataset) to get its ID.
- <a id="validate-and-explain-with-the-dataset"></a>[Validate and explain with the dataset](use-local-api.md#validate-and-explain-with-the-dataset) to check the resolved window.
- <a id="save-and-update-a-draft"></a>[Save and update a draft](use-local-api.md#save-and-update-a-draft) to store strategy source.

An update requires the current `If-Match` ETag and the `expected_revision` number. A source change creates a revision and a new ETag. A rename changes the ETag and preserves the revision number. An identical update preserves both.

Archiving with DELETE and the current ETag returns HTTP 204. The draft disappears from the active list and its detail route returns HTTP 404. Its revision list and saved revisions remain readable.

## Routes

The running service's [OpenAPI document](http://127.0.0.1:8000/openapi.json) describes the request and response schemas. The table uses paths relative to `/api/v1`. `{ident}` is a strategy or dataset identifier, and `{revision}` is the strategy revision number.

| Method and path | Behavior |
| --- | --- |
| `POST /strategies/validate` | Compile source and optionally validate window compatibility. |
| `POST /strategies/explain` | Explain the compiled source and assumptions. |
| `GET /strategies`, `POST /strategies` | List active drafts or save a new draft. The optional `q` query parameter matches substrings of the draft name, case-insensitively. |
| `GET /strategies/{ident}` | Read the current draft and ETag. |
| `PUT /strategies/{ident}` | Send `name`, `source`, and `expected_revision` with the current `If-Match` ETag. |
| `DELETE /strategies/{ident}` | Archive the draft with the current `If-Match` ETag. |
| `GET /strategies/{ident}/revisions`, `GET /strategies/{ident}/revisions/{revision}` | List or read saved source revisions. |
| `GET /datasets`, `GET /datasets/{ident}` | List imports or read metadata, quality, and a row preview. |
| `POST /datasets/import` | Upload one `file` and one `metadata` JSON part. |

Library routes require the supervised service. List routes accept `limit` from 1 to 500 (default 50). They return `items`, `next_cursor`, and `snapshot`, the creation-time cutoff used for pagination. Pass `next_cursor` as an opaque `cursor` on the same list route and with the same filters. A null `next_cursor` marks the last page.

## Dataset import identity

A new import returns HTTP 201 with `deduplicated: false`. A repeat upload with the same file bytes and validated metadata returns HTTP 200 with `deduplicated: true` and the original dataset ID. The filename can change without affecting this check.

Use `dataset_hash` to compare normalized candles and semantic metadata across imports. A separate upload with `timeframe` written as `24h` instead of `1d` creates a new ID with the same hash. Equivalent CSV and Parquet uploads can also have distinct IDs and share a hash. See [the dataset hash contract](results.md#compare-and-replay-runs).

## Handle errors

For HTTP errors from inspection and library routes, read `error.code` and `error.message`. The JSON response also includes `schema_version: 1`, a `request_id`, and `error.diagnostics` and `error.retryable`. Dataset validation failures may include row diagnostics. To see the status, headers, and error body in `curl`, use `-i` and omit `-f`. For inspection responses with HTTP 200, read the top-level `valid` and `diagnostics` fields.

| HTTP status | What to check |
| --- | --- |
| 400 | Fix malformed JSON or multipart data. An invalid cursor or a cursor used with different filters also returns 400. |
| 403 | Verify the loopback address and the required `Origin` on writes. |
| 404 | Check the resource ID. Inspection with an unknown dataset ID returns `E_DATASET_NOT_FOUND`. |
| 409 | The ETag or revision is stale. Read the draft again before retrying the update or archive. |
| 413, 415, 422 | Check size limits, media type, or request fields. Strategy source is capped at 64 KiB of UTF-8 and JSON requests at 128 KiB. For candle file limits, see [Candle data](candle-data.md#file-formats). |
| 428 | Send the required `If-Match` header when updating or archiving a draft. |
| 429 | The editor is rate-limited or the import capacity is full. Wait the number of seconds in the `Retry-After` header before retrying. |
