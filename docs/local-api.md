# Local HTTP API

Use the optional HTTP service to inspect strategy source, save drafts, and import datasets. Run simulations with the [CLI](cli.md#backtest).

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

The service accepts loopback requests at `127.0.0.1:8000`. Use this address in requests because the Host header is checked. For POST, PUT, and DELETE, send `Origin: http://127.0.0.1:3000`. Use `Content-Type: application/json` for JSON writes and multipart for dataset uploads. Use Ctrl-C in the service terminal to stop it.

For source-only inspection, start `tradelang-api` on the same port after stopping the supervisor. The standalone service has the two editor endpoints and reports degraded health because it runs without a worker. The supervisor persists drafts and datasets under `--data-root`. If its worker stops, `/health` returns HTTP 503 while editor routes remain available.

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

## Routes

The running service's [OpenAPI document](http://127.0.0.1:8000/openapi.json) describes the request and response schemas. Paths in the table are relative to `/api/v1`.

| Method and path | Behavior |
| --- | --- |
| `POST /strategies/validate` | Compile source and optionally validate window compatibility. |
| `POST /strategies/explain` | Explain the compiled source and assumptions. |
| `GET /strategies`, `POST /strategies` | List active drafts or save a new draft. The optional `q` query parameter matches substrings of the draft name, case-insensitively. |
| `GET /strategies/{id}` | Read the current draft and ETag. |
| `PUT /strategies/{id}` | Send `name`, `source`, and `expected_revision` with the current `If-Match` ETag. |
| `DELETE /strategies/{id}` | Archive the draft with the current `If-Match` ETag. |
| `GET /strategies/{id}/revisions`, `GET /strategies/{id}/revisions/{revision}` | List or read saved source revisions. |
| `GET /datasets`, `GET /datasets/{id}` | List imports or read metadata, quality, and a row preview. |
| `POST /datasets/import` | Upload one `file` and one `metadata` JSON part. |

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
