# Use the local HTTP API

Start the supervised service, send a strategy for validation, and check which candles it can use. You can also save the source as a draft. Before you begin, open the TradeLang checkout and install [uv](https://docs.astral.sh/uv/getting-started/installation/). The examples use two POSIX shell terminals and `curl`.

## Start the service

From the checkout root in the first terminal, install TradeLang with the optional API dependencies. Start the supervisor with a fresh library directory.

```sh
uv tool install --python 3.12 '.[api]' --reinstall
library_root=$(mktemp -d "${TMPDIR:-/tmp}/tradelang-library.XXXXXX")
tradelang-local --data-root "$library_root"
```

In the second terminal, check that the worker is available.

```sh
curl -fsS http://127.0.0.1:8000/health
```

Expect `"status":"ok"` and `"worker_available":true`. Use `127.0.0.1:8000` in the requests so the Host header matches. Keep the first terminal running for the rest of the guide. See the [API reference](local-api.md#start-the-service) for standalone mode and request headers.

## Validate or explain source

From the checkout root in the second terminal, put the [quickstart strategy](fixtures/core.trade) into a JSON request. Reuse the variables in this terminal in the later steps.

```sh
api=http://127.0.0.1:8000/api/v1
origin=http://127.0.0.1:3000
payload=$(uv run --no-project --python 3.12 python - <<'PY'
import json
from pathlib import Path

source = Path("docs/fixtures/core.trade").read_bytes().decode("utf-8")
print(json.dumps({"source": source}))
PY
)
curl -fsS "$api/strategies/validate" \
  -H "Origin: $origin" -H 'Content-Type: application/json' \
  --data-binary "$payload"
```

Expect `valid: true`, `warmup_index: 0`, and a typed `spec`. The `resolved_window` is null because the request supplied source only. Send the same body to `/strategies/explain` to read the normalized rules in `text` and the execution assumptions in `assumptions`.

## Save a draft and import candles

The next requests use the fresh library created by the supervisor. A dataset ID identifies an import. A draft is a saved copy of the strategy source.

### Import and select a dataset

Upload the [sample candles](fixtures/core.csv) and [metadata](fixtures/metadata.json) as multipart form data. Read the imported ID from the response.

```sh
imported=$(curl -fsS "$api/datasets/import" -H "Origin: $origin" \
  -F 'file=@docs/fixtures/core.csv' -F 'metadata=<docs/fixtures/metadata.json')
printf '%s\n' "$imported"
dataset_id=$(printf '%s\n' "$imported" | uv run --no-project --python 3.12 \
  python -c 'import json, sys; print(json.load(sys.stdin)["dataset"]["id"])')
```

The first import returns HTTP 201 with `deduplicated: false` and a `dataset.id`. If you repeat the same upload, expect the same ID and `deduplicated: true`. See [dataset identity](local-api.md#dataset-import-identity) to compare different imports.

### Validate and explain with the dataset

Add the imported ID to the strategy request and send it to both endpoints.

```sh
with_dataset=$(printf '%s\n' "$payload" | uv run --no-project --python 3.12 \
  python -c 'import json, sys; print(json.dumps(dict(json.load(sys.stdin), dataset_id=sys.argv[1])))' \
  "$dataset_id")
for command in validate explain; do
  curl -fsS "$api/strategies/$command" \
    -H "Origin: $origin" -H 'Content-Type: application/json' \
    --data-binary "$with_dataset"
  printf '\n'
done
```

In both responses, expect `valid: true` and this `resolved_window`. In the validation response, also check that `data_compatible` is true.

```json
{
  "first_open": "2024-01-01T00:00:00Z",
  "last_close_at": "2024-01-04T00:00:00Z",
  "readiness_index": 0,
  "first_signal_at": "2024-01-02T00:00:00Z",
  "first_execution_at": "2024-01-02T00:00:00Z"
}
```

For a well-formed request with an invalid strategy or mismatched data, the API can return HTTP 200 with `valid: false`. To try this on the fixture, change `market TESTUSDT` to `market OTHERUSDT` in the request's `source`. Expect `E402_WINDOW` in `diagnostics` and a null `resolved_window`. Restore the market and retry to confirm compatibility. A well-formed dataset UUID absent from the library returns HTTP 404 with `E_DATASET_NOT_FOUND`. See [Handle errors](local-api.md#handle-errors) for the response shape.

### Save and update a draft

Save a draft named `Quickstart example`. Inspect the response and keep its ID and version information.

```sh
draft=$(printf '%s\n' "$payload" | uv run --no-project --python 3.12 \
  python -c 'import json, sys; print(json.dumps(dict(json.load(sys.stdin), name="Quickstart example")))')
saved=$(curl -fsS "$api/strategies" \
  -H "Origin: $origin" -H 'Content-Type: application/json' \
  --data-binary "$draft")
printf '%s\n' "$saved"
```

Creation returns HTTP 201 with `Location` and `ETag` headers. The response body includes `id`, `etag`, and `current_revision: 1`. Use those values to rename the draft without editing its source.

```sh
strategy_id=$(printf '%s\n' "$saved" | uv run --no-project --python 3.12 \
  python -c 'import json, sys; print(json.load(sys.stdin)["id"])')
etag=$(printf '%s\n' "$saved" | uv run --no-project --python 3.12 \
  python -c 'import json, sys; print(json.load(sys.stdin)["etag"])')
updated=$(printf '%s\n' "$saved" | uv run --no-project --python 3.12 python -c '
import json, sys
draft = json.load(sys.stdin)
print(json.dumps(dict(name="Renamed example", source=draft["current_source"],
                      expected_revision=draft["current_revision"])))
')
curl -fsS -X PUT "$api/strategies/$strategy_id" \
  -H "Origin: $origin" -H 'Content-Type: application/json' -H "If-Match: $etag" \
  --data-binary "$updated"
```

The response has the new name and a new ETag. The revision stays at 1 because the source matches the saved revision. If you repeat the update with the old ETag, expect HTTP 409. Fetch the draft again before retrying. See the [route reference](local-api.md#routes) for reading, archiving, and listing revisions.

When finished, press Ctrl+C in the first terminal to stop the supervisor. To simulate the checked strategy, use the [CLI backtest command](cli.md#backtest).
