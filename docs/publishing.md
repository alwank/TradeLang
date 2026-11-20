# Build and publish the documentation

## Build locally

From the repository root, use the isolated docs dependencies. The documentation build only needs the packages in `docs/requirements.txt`.

```sh
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs serve
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs build --strict
```

The preview runs at `http://127.0.0.1:8000/`. If the local API occupies that port, add `--dev-addr 127.0.0.1:8001` to the preview command. The strict build writes HTML to `site/` and checks navigation, links, and anchors. GitHub Actions runs the same build.

## What to publish

| Location | Include | Keep out |
| --- | --- | --- |
| Public repository | Runtime source and migrations, grammar and schemas, `pyproject.toml`, `uv.lock`, tests, CI workflows, synthetic fixtures and strategies, the example generator, and docs source and build config. Add a license, changelog, and short contributor instructions for the first release. | Credentials, environment files with secrets, customer or broker exports, private strategies, unlicensed vendor candles, local databases, and generated runs, wheels, caches, and HTML. Run bundles include original source and market data. |
| Read the Docs | Quickstart, runnable examples, language and indicator reference, execution rules and limitations, data and command references, result interpretation, and the current local API. Publish grammar and typed schema alongside their reference pages. | Internal handoffs, risk registers, audit drafts, speculative endpoint contracts, setup notes tied to one machine, and claims about returns from synthetic examples. |

Before the first public push, confirm that `LICENSE` and the package metadata reflect the chosen license. Review the exact staged files with `git diff --cached --name-only`. MkDocs exclusions control the generated site only. Files committed to a public repository are visible even if they never appear on the site.

Keep milestone drafts, early verification reports, and draft endpoint contracts in private project notes. If you publish a design decision, update its status and links first. Use release notes to record user-visible changes to the language, simulation assumptions, and artifact schemas.

## Publish to Read the Docs

1. Open a GitHub pull request against `main`. Wait for GitHub Actions and the Read the Docs check, then use the Read the Docs check link to inspect the preview.
2. Merge the pull request. Read the Docs builds the `latest` version from `main` using `.readthedocs.yaml` and `mkdocs.yml`.
3. Check that the `latest` build for the merge commit succeeds, then open the changed pages on the public site. [Build history](https://app.readthedocs.org/projects/tradelang/builds/) · [Published docs](https://tradelang.readthedocs.io/en/latest/)

When publishing a tagged release, verify that Read the Docs builds the matching version. The `stable` version can serve as the default for released documentation. [Read the Docs versioning](https://docs.readthedocs.com/platform/stable/versions.html)
