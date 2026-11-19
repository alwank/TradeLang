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

## Connect Read the Docs

1. Push the reviewed repository with `mkdocs.yml`, `.readthedocs.yaml`, and the docs source on its default branch.
2. In Read the Docs Community, connect the repository through the Git provider integration and add it as a project. Set the default branch to the branch you pushed, typically `main`. [Add a documentation project](https://docs.readthedocs.com/platform/stable/intro/add-project.html)
3. Check that the `latest` build succeeds and open its site. Add the assigned documentation URL to the repository README and package metadata after confirming it. [Read the Docs tutorial](https://docs.readthedocs.com/platform/stable/tutorial/)
4. Tag the first release once it's ready. Verify that Read the Docs builds the matching version, then use `stable` as the default when you want the site to open on the released docs. Keep `latest` for the default branch. [Read the Docs versioning](https://docs.readthedocs.com/platform/stable/versions.html)
