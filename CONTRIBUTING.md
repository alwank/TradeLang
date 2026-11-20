# Contributing to TradeLang

## Set up and run checks

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run these commands from the repository root. The lockfile selects Python 3.12 and dependency versions.

```sh
uv sync --locked --extra api
uv run --locked --extra api pytest
uv run --locked --extra api ruff check src tests scripts
uv run --locked --extra api mypy src
```

The [GitHub Actions workflow](.github/workflows/test.yml) runs the standard suite against both the source checkout and the installed wheel. Its `language-deep` job runs deeper conformance, property, and fuzz checks on a weekly schedule and when the workflow is triggered manually.

Use the [three-candle quickstart](docs/quickstart.md) to inspect signal order, fills, and final equity by hand. Put local experiments and run bundles under `runs/`.

## Change the language or simulator

- When editing the runtime grammar or typed strategy schema, update the matching reference file in `docs/`. The tests check both copies.
- When a change affects signals, indicator values, fills, or accounting, update the affected golden cases and review whether the execution semantics version needs to change.
- Update the relevant reference and the [changelog](CHANGELOG.md) for user-visible changes.

## Submit changes

Describe the expected behavior, provide a reproducible example using synthetic inputs, and list the checks you ran. Share a minimal strategy and candle sample for backtest issues. Review any attached bundle for private data because it contains the exact submitted strategy and candles.

Run the strict documentation build when editing the docs.

```sh
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs build --strict
```
